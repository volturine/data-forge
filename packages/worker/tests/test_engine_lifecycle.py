from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import pytest

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import (
    ENGINE_ADMISSION_PRIORITY_INTERACTIVE,
    ENGINE_ADMISSION_PRIORITY_LIFECYCLE,
    EngineCapacityFull,
    ProcessManager,
)
from runtime.config import settings
from runtime.domain.compute.base import ComputeEngine


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

    @property
    def last_known_alive(self) -> bool:
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


def test_process_manager_keeps_shutdown_container_owned_until_cleanup_finishes() -> None:
    shutdown_started = threading.Event()
    release_shutdown = threading.Event()

    class ContainerEngine(_FakeEngine):
        @property
        def container_id(self) -> str:
            return "container-being-shutdown"

        def shutdown(self) -> None:
            shutdown_started.set()
            assert release_shutdown.wait(timeout=2)
            super().shutdown()

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, ContainerEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-shutdown-ownership")
    try:
        manager.spawn_engine(identity)
        shutdown = threading.Thread(target=manager.shutdown_engine, args=(identity,))
        shutdown.start()
        assert shutdown_started.wait(timeout=2)
        assert manager._managed_container_ids() == {"container-being-shutdown"}

        release_shutdown.set()
        shutdown.join(timeout=2)
        assert not shutdown.is_alive()
        assert manager._managed_container_ids() == set()
    finally:
        release_shutdown.set()
        manager.shutdown_all()


def test_process_manager_serializes_same_identity_spawn_after_shutdown() -> None:
    shutdown_started = threading.Event()
    allow_shutdown = threading.Event()
    created: list[_FakeEngine] = []

    class BlockingShutdownEngine(_FakeEngine):
        def __init__(self, resource_id: str, *, block_shutdown: bool) -> None:
            super().__init__(resource_id)
            self.block_shutdown = block_shutdown

        def shutdown(self) -> None:
            if self.block_shutdown:
                shutdown_started.set()
                assert allow_shutdown.wait(timeout=2)
            super().shutdown()

    def factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None = None):
        engine = BlockingShutdownEngine(identity.resource_id, block_shutdown=not created)
        created.append(engine)
        return cast(Any, engine)

    identity = _analysis_identity("analysis-shutdown-restart")
    manager = ProcessManager(engine_factory=factory)
    try:
        original = manager.spawn_engine(identity).engine
        with ThreadPoolExecutor(max_workers=2) as executor:
            shutdown = executor.submit(manager.shutdown_engine, identity)
            assert shutdown_started.wait(timeout=2)

            replacement = executor.submit(manager.spawn_engine, identity)
            time.sleep(0.05)
            assert not replacement.done()

            allow_shutdown.set()
            shutdown.result(timeout=2)
            restarted = replacement.result(timeout=2).engine

        assert restarted is not original
        assert restarted.is_process_alive()
    finally:
        allow_shutdown.set()
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
async def test_admitted_reused_engine_is_not_evicted_before_execution(monkeypatch) -> None:
    """An admitted request keeps its existing engine alive until its runner starts."""
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-admitted-existing")
    second_identity = _analysis_identity("analysis-admitted-other")
    try:
        manager.spawn_engine(first_identity)
        owns_admission = await manager.await_spawn_admission(first_identity)
        assert owns_admission is False
        manager.reserve_engine_request(first_identity)

        with pytest.raises(EngineCapacityFull):
            manager.spawn_engine(second_identity)
        assert manager.get_engine(first_identity) is not None

        manager.release_engine_request(first_identity)
        manager.spawn_engine(second_identity)
        assert manager.get_engine(first_identity) is None
    finally:
        manager.release_spawn_admission(first_identity, owned=owns_admission)
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
async def test_process_manager_capacity_admission_prioritizes_interactive_work(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    running = _analysis_identity("analysis-priority-running")
    lifecycle = _analysis_identity("analysis-priority-lifecycle")
    interactive = _analysis_identity("analysis-priority-interactive")
    order: list[str] = []

    async def admit_spawn_stop(identity: compute_pb2.EngineIdentity, priority: int) -> None:
        owns_admission = await manager.await_spawn_admission(identity, priority=priority)
        try:
            await asyncio.to_thread(manager.spawn_engine, identity)
            order.append(identity.resource_id)
            await asyncio.to_thread(manager.shutdown_engine, identity)
        finally:
            manager.release_spawn_admission(identity, owned=owns_admission)

    try:
        with manager.acquire_engine(running):
            lifecycle_task = asyncio.create_task(admit_spawn_stop(lifecycle, ENGINE_ADMISSION_PRIORITY_LIFECYCLE))
            await asyncio.sleep(0.02)
            interactive_task = asyncio.create_task(admit_spawn_stop(interactive, ENGINE_ADMISSION_PRIORITY_INTERACTIVE))
            await asyncio.sleep(0.05)
            assert order == []
        await asyncio.wait_for(asyncio.gather(lifecycle_task, interactive_task), timeout=2)
        assert order == [interactive.resource_id, lifecycle.resource_id]
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


class _FakeWarmEngine(_FakeEngine):
    def __init__(self, resource_id: str = "", resource_config: dict | None = None) -> None:
        super().__init__(resource_id, resource_config)
        self.bound_identities: list[compute_pb2.EngineIdentity] = []
        self._is_warm = not bool(resource_id)

    def bind_identity(self, identity: compute_pb2.EngineIdentity, *, resource_config: dict | None = None, namespace: str | None = None) -> None:
        self.analysis_id = identity.resource_id
        self.bound_identities.append(identity)
        self._is_warm = False

    @property
    def is_warm(self) -> bool:
        return self._is_warm


def test_process_manager_warm_pool_replenishes_and_claims(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_warm_pool_size", 2)
    monkeypatch.setattr(settings, "max_concurrent_engines", 3)

    created_warm: list[_FakeWarmEngine] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmEngine()
        created_warm.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_engine_factory=warm_factory,
    )

    try:
        # Wait for warm pool to replenish up to 2
        for _ in range(50):
            if len(manager._warm_pool) == 2:
                break
            time.sleep(0.02)
        assert len(manager._warm_pool) == 2
        assert len(created_warm) == 2
        assert all(w.is_process_alive() for w in created_warm)

        # Spawn engine 1 -> should claim from warm pool
        id1 = _analysis_identity("analysis-claimed-1")
        info1 = manager.spawn_engine(id1)
        claimed_engine = cast(_FakeWarmEngine, info1.engine)
        assert claimed_engine in created_warm
        assert claimed_engine.bound_identities == [id1]
        assert not claimed_engine.is_warm

        # Replenisher should create 1 more warm engine to get back to 2 (total 1 live + 2 warm = 3)
        for _ in range(50):
            if len(manager._warm_pool) == 2 and len(created_warm) == 3:
                break
            time.sleep(0.02)
        assert len(manager._warm_pool) == 2
        assert len(created_warm) == 3

        # Spawn engine 2 -> claims another warm engine (total 2 live + 1 warm = 3)
        id2 = _analysis_identity("analysis-claimed-2")
        info2 = manager.spawn_engine(id2)
        assert cast(_FakeWarmEngine, info2.engine) in created_warm

        # Cannot replenish beyond max_concurrent_engines (3 total)
        time.sleep(0.1)
        assert len(manager._warm_pool) <= 1
    finally:
        manager.shutdown_all()
        assert all(not w.is_process_alive() for w in created_warm)


def test_process_manager_can_disable_warm_pool(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_warm_pool_size", 2)
    created_warm: list[_FakeWarmEngine] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmEngine()
        created_warm.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_engine_factory=warm_factory,
        warm_pool_size=0,
    )

    try:
        time.sleep(0.05)
        assert len(manager._warm_pool) == 0
        assert created_warm == []
        assert manager._warm_replenish_thread is None
    finally:
        manager.shutdown_all()


def test_capacity_decisions_never_probe_the_engine_runtime(monkeypatch) -> None:
    """Capacity scans run under the engines lock, so they must not do engine I/O.

    A container inspection or engine RPC can hang for as long as a container
    boot takes. When a capacity scan performs one, every claim, release and
    status call in the worker queues behind it.
    """
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    hang_probes = threading.Event()
    probe_started = threading.Event()
    release_probe = threading.Event()

    class HangingProbeEngine(_FakeEngine):
        def is_process_alive(self) -> bool:
            if hang_probes.is_set():
                probe_started.set()
                release_probe.wait(10)
            return self._alive

    busy = HangingProbeEngine("analysis-busy")
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, busy))
    try:
        manager.spawn_engine(_analysis_identity("analysis-busy"))
        busy.current_job_id = "job-1"

        # Somebody (idle reaper, status refresh) is inside a stuck probe.
        hang_probes.set()
        stuck = threading.Thread(target=busy.is_process_alive, daemon=True)
        stuck.start()
        assert probe_started.wait(2)

        started = time.monotonic()
        assert manager.can_admit_spawn() is False
        assert time.monotonic() - started < 1.0
    finally:
        release_probe.set()
        hang_probes.clear()
        manager.shutdown_all()


def test_busy_engine_is_not_evicted_or_reaped_after_liveness_failure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_concurrent_engines", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-busy-after-heartbeat-failure")
    try:
        info = manager.spawn_engine(identity)
        info.engine.current_job_id = "job-running"
        cast(Any, info.engine)._alive = False
        manager._idle_ttl_seconds = 0

        assert manager.can_admit_spawn() is False
        manager._reap_idle_engines_once()

        assert manager.get_engine(identity) is info.engine
    finally:
        manager.shutdown_all()


def test_dead_engine_is_restarted_instead_of_reused(monkeypatch) -> None:
    created: list[_FakeEngine] = []

    def factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None) -> _FakeEngine:
        engine = _FakeEngine(identity.resource_id, resource_config)
        created.append(engine)
        return engine

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, factory(identity, resource_config)))
    identity = _analysis_identity("analysis-restart-after-failure")
    try:
        first = manager.spawn_engine(identity)
        cast(Any, first.engine)._alive = False

        second = manager.spawn_engine(identity)

        assert second.engine is not first.engine
        assert len(created) == 2
        assert manager.get_engine(identity) is second.engine
    finally:
        manager.shutdown_all()


def test_engine_status_reads_tracked_liveness_without_probing() -> None:
    class CountingEngine(_FakeEngine):
        def __init__(self, resource_id: str, resource_config: dict | None = None) -> None:
            super().__init__(resource_id, resource_config)
            self.probes = 0

        def is_process_alive(self) -> bool:
            self.probes += 1
            return self._alive

        def check_health(self) -> bool:
            self.probes += 1
            return self._alive

    engine = CountingEngine("analysis-status")
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, engine))
    try:
        identity = _analysis_identity("analysis-status")
        manager.spawn_engine(identity)
        probes_after_spawn = engine.probes

        status = manager.get_engine_status(identity)

        assert status.status == "healthy"
        assert engine.probes == probes_after_spawn
    finally:
        manager.shutdown_all()


def test_warm_pool_never_reserves_beyond_max_concurrent_engines(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_warm_pool_size", 4)
    monkeypatch.setattr(settings, "max_concurrent_engines", 2)

    created: list[_FakeWarmEngine] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmEngine()
        created.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_engine_factory=warm_factory,
    )
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(manager._warm_pool) < 2:
            time.sleep(0.02)

        assert len(manager._warm_pool) == 2
        # The whole deficit is spawned at once, so the batch has to fit in the
        # remaining capacity; a warm pool larger than the cap starves real work.
        time.sleep(0.2)
        assert len(created) == 2
        assert manager._capacity_starts == 0
    finally:
        manager.shutdown_all()
