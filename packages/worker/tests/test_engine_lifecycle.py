from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import pytest

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import EngineCapacityFull, ProcessManager
from runtime.config import settings


class _FakeEngine:
    def __init__(self, resource_id: str, resource_config: dict | None = None) -> None:
        self.analysis_id = resource_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, object] = {}
        self.current_job_id: str | None = None
        self._alive = False
        self._capacity_notifier = None

    def bind_capacity_notifier(self, notifier) -> None:
        self._capacity_notifier = notifier

    @property
    def process_id(self) -> int | None:
        return 1234

    def start(self) -> None:
        self._alive = True

    def is_process_alive(self) -> bool:
        return self._alive

    def check_health(self) -> bool:
        return self._alive

    def preview(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def export(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def get_schema(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def get_row_count(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def get_result(self, timeout: float = 1.0, job_id: str | None = None):
        raise NotImplementedError

    def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None):
        raise NotImplementedError

    def shutdown(self) -> None:
        self._alive = False
        if self._capacity_notifier is not None:
            self._capacity_notifier()


def test_process_manager_reaps_idle_shared_engines(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_idle_ttl_seconds", 1)
    monkeypatch.setattr(settings, "engine_idle_reap_interval_seconds", 1)

    def fake_engine_factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None = None):
        return cast(Any, _FakeEngine(identity.resource_id, resource_config))

    manager = ProcessManager(engine_factory=fake_engine_factory)
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id="analysis-1",
        resource_id="analysis-1",
    )
    try:
        manager.spawn_engine(identity)
        assert manager.get_engine(identity) is not None

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and manager.get_engine(identity) is not None:
            time.sleep(0.05)

        assert manager.get_engine(identity) is None
    finally:
        manager.shutdown_all()


def test_process_manager_shutdown_stops_real_engine_subprocess() -> None:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id="analysis-shutdown",
        resource_id="analysis-shutdown",
    )
    manager = ProcessManager(engine_factory=lambda identity, resource_config: PolarsComputeEngine(identity.resource_id, resource_config))
    engine = manager.spawn_engine(identity).engine
    try:
        assert engine.is_process_alive()

        manager.shutdown_engine(identity)

        assert manager.get_engine(identity) is None
        assert not engine.is_process_alive()
    finally:
        manager.shutdown_all()


def _analysis_identity(resource_id: str) -> compute_pb2.EngineIdentity:
    return compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        analysis_id=resource_id,
        resource_id=resource_id,
    )


def test_process_manager_starts_distinct_engines_concurrently() -> None:
    start_barrier = threading.Barrier(3)

    class ConcurrentStartEngine(_FakeEngine):
        def start(self) -> None:
            start_barrier.wait(timeout=2)
            super().start()

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, ConcurrentStartEngine(identity.resource_id, resource_config)))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(manager.spawn_engine, _analysis_identity("analysis-concurrent-1"))
            second = executor.submit(manager.spawn_engine, _analysis_identity("analysis-concurrent-2"))
            start_barrier.wait(timeout=2)
            assert first.result(timeout=2).engine.is_process_alive()
            assert second.result(timeout=2).engine.is_process_alive()
    finally:
        manager.shutdown_all()


def test_process_manager_defers_when_start_holds_capacity(monkeypatch) -> None:
    """In-flight starts hold a ticket; further spawns raise without blocking the runner."""
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    start_entered = threading.Event()
    release_start = threading.Event()

    class BlockingStartEngine(_FakeEngine):
        def start(self) -> None:
            start_entered.set()
            assert release_start.wait(timeout=2)
            super().start()

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, BlockingStartEngine(identity.resource_id, resource_config)))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(manager.spawn_engine, _analysis_identity("analysis-capacity-1"))
            assert start_entered.wait(timeout=2)
            second = executor.submit(manager.spawn_engine, _analysis_identity("analysis-capacity-2"))
            with pytest.raises(EngineCapacityFull):
                second.result(timeout=2)
            release_start.set()
            first.result(timeout=2)
            # Slot free / idle: next spawn can proceed (evict if needed).
            second_info = manager.spawn_engine(_analysis_identity("analysis-capacity-2"))
            assert second_info.engine.is_process_alive()
    finally:
        release_start.set()
        manager.shutdown_all()


def test_process_manager_defers_while_engine_is_reserved(monkeypatch) -> None:
    """Reservations block eviction; spawn raises so the runner can leave the pool."""
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-reserved-1")
    second_identity = _analysis_identity("analysis-reserved-2")
    try:
        with manager.acquire_engine(first_identity) as first_engine:
            assert first_engine.is_process_alive()
            with pytest.raises(EngineCapacityFull):
                manager.spawn_engine(second_identity)

        second_info = manager.spawn_engine(second_identity)
        assert second_info.engine.is_process_alive()
        assert manager.get_engine(first_identity) is None
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_wait_for_capacity_then_spawn(monkeypatch) -> None:
    """Proper queue: park async without a runner, then claim when capacity frees."""
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-async-1")
    second_identity = _analysis_identity("analysis-async-2")
    try:
        with manager.acquire_engine(first_identity):
            with pytest.raises(EngineCapacityFull):
                manager.spawn_engine(second_identity)

            wait_task = asyncio.create_task(manager.wait_for_capacity())
            await asyncio.sleep(0.05)
            assert not wait_task.done()

        await asyncio.wait_for(wait_task, timeout=2)
        second_info = manager.spawn_engine(second_identity)
        assert second_info.engine.is_process_alive()
        assert manager.get_engine(first_identity) is None
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_capacity_admission_is_fifo(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first = _analysis_identity("analysis-fifo-1")
    second = _analysis_identity("analysis-fifo-2")
    third = _analysis_identity("analysis-fifo-3")
    order: list[str] = []

    async def admit_spawn_stop(identity: compute_pb2.EngineIdentity) -> None:
        owns_admission = await manager.await_spawn_admission(identity)
        try:
            await asyncio.to_thread(manager.spawn_engine, identity)
            order.append(identity.resource_id)
            await asyncio.sleep(0)
            await asyncio.to_thread(manager.shutdown_engine, identity)
        finally:
            manager.release_spawn_admission(identity, owned=owns_admission)

    try:
        with manager.acquire_engine(first):
            second_task = asyncio.create_task(admit_spawn_stop(second))
            await asyncio.sleep(0.02)
            third_task = asyncio.create_task(admit_spawn_stop(third))
            await asyncio.sleep(0.05)
            assert order == []
        await asyncio.wait_for(asyncio.gather(second_task, third_task), timeout=2)
        assert order == [second.resource_id, third.resource_id]
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_shutdown_rejects_capacity_waiter(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    running = manager.spawn_engine(_analysis_identity("analysis-running"))
    running.engine.current_job_id = "job-running"
    waiter = asyncio.create_task(manager.await_spawn_admission(_analysis_identity("analysis-waiting")))
    await asyncio.sleep(0.02)

    await asyncio.to_thread(manager.shutdown_all)

    with pytest.raises(RuntimeError, match="shut down"):
        await asyncio.wait_for(waiter, timeout=1)


@pytest.mark.asyncio
async def test_same_identity_prewarm_shares_pending_admission(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-shared-admission")
    try:
        outer_owns = await manager.await_spawn_admission(identity)
        prewarm_owns = await asyncio.wait_for(manager.await_spawn_admission(identity), timeout=1)

        assert outer_owns is True
        assert prewarm_owns is False
        await asyncio.to_thread(manager.spawn_engine, identity)
        manager.release_spawn_admission(identity, owned=outer_owns)
        manager.release_spawn_admission(identity, owned=prewarm_owns)
        assert manager.get_engine(identity) is not None
    finally:
        manager.shutdown_all()
