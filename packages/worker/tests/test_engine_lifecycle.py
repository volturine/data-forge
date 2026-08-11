from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import ProcessManager
from runtime.config import settings


class _FakeEngine:
    def __init__(self, resource_id: str, resource_config: dict | None = None) -> None:
        self.analysis_id = resource_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, object] = {}
        self.current_job_id: str | None = None
        self._alive = False

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


def test_process_manager_queues_while_start_holds_capacity(monkeypatch) -> None:
    """In-flight starts hold a ticket; further spawns queue until a slot frees."""
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
            time.sleep(0.15)
            assert not second.done()
            release_start.set()
            first.result(timeout=2)
            # First is idle after start → second evicts it and starts.
            second_info = second.result(timeout=2)
            assert second_info.engine.is_process_alive()
            assert manager.get_engine(_analysis_identity("analysis-capacity-1")) is None
            assert manager.get_engine(_analysis_identity("analysis-capacity-2")) is second_info.engine
    finally:
        release_start.set()
        manager.shutdown_all()


def test_process_manager_queues_while_engine_is_reserved(monkeypatch) -> None:
    """Reservations block eviction; waiters queue until the reservation clears."""
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-reserved-1")
    second_identity = _analysis_identity("analysis-reserved-2")
    try:
        hold = threading.Event()
        released = threading.Event()

        def hold_first() -> None:
            with manager.acquire_engine(first_identity) as first_engine:
                released.set()
                assert first_engine.is_process_alive()
                assert hold.wait(timeout=2)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(hold_first)
            assert released.wait(timeout=2)
            second_future = executor.submit(manager.spawn_engine, second_identity)
            time.sleep(0.15)
            assert not second_future.done()
            hold.set()
            first_future.result(timeout=2)
            second_info = second_future.result(timeout=2)
            assert second_info.engine.is_process_alive()
            assert manager.get_engine(first_identity) is None
    finally:
        hold.set()
        manager.shutdown_all()


def test_process_manager_capacity_queue_is_fifo(monkeypatch) -> None:
    """Queued spawns claim free slots in arrival order."""
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-fifo-1")
    second_identity = _analysis_identity("analysis-fifo-2")
    third_identity = _analysis_identity("analysis-fifo-3")
    try:
        hold = threading.Event()
        released = threading.Event()
        order: list[str] = []
        order_lock = threading.Lock()

        def hold_first() -> None:
            with manager.acquire_engine(first_identity):
                released.set()
                assert hold.wait(timeout=3)

        def spawn_and_record(identity: compute_pb2.EngineIdentity) -> None:
            info = manager.spawn_engine(identity)
            with order_lock:
                order.append(identity.resource_id)
            # Hold the ticket briefly so the next waiter cannot overtake before we record.
            time.sleep(0.05)
            manager.shutdown_engine(identity)
            assert info.engine.is_process_alive() is False

        with ThreadPoolExecutor(max_workers=3) as executor:
            first_future = executor.submit(hold_first)
            assert released.wait(timeout=2)
            second_future = executor.submit(spawn_and_record, second_identity)
            time.sleep(0.05)
            third_future = executor.submit(spawn_and_record, third_identity)
            time.sleep(0.1)
            assert not second_future.done()
            assert not third_future.done()
            hold.set()
            first_future.result(timeout=2)
            second_future.result(timeout=2)
            third_future.result(timeout=2)
            assert order == ["analysis-fifo-2", "analysis-fifo-3"]
    finally:
        hold.set()
        manager.shutdown_all()
