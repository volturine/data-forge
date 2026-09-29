from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, cast

import pytest

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_engine import PolarsComputeEngine
from runtime.compute_manager import (
    _ENGINE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS,
    ENGINE_ADMISSION_PRIORITY_INTERACTIVE,
    ENGINE_ADMISSION_PRIORITY_LIFECYCLE,
    EngineCapacityFull,
    EngineInfo,
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
        self.cancelled_jobs: list[str | None] = []

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

    def cancel_job(self, job_id: str | None = None) -> bool:
        self.cancelled_jobs.append(job_id)
        return True

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


def test_reusing_engine_does_not_republish_unchanged_snapshot() -> None:
    snapshots: list[list[object]] = []
    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        on_snapshot=snapshots.append,
        warm_worker_target=0,
    )
    identity = _analysis_identity("analysis-snapshot-reuse")
    try:
        first = manager.spawn_engine(identity)
        assert len(snapshots) == 1

        reused = manager.spawn_engine(identity)

        assert reused is first
        assert len(snapshots) == 1

        first._last_snapshot_at = time.monotonic() - _ENGINE_ACTIVITY_SNAPSHOT_INTERVAL_SECONDS - 1
        manager.spawn_engine(identity)

        assert len(snapshots) == 2
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_existing_engine_request_admission_is_released_exactly_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_target=0,
    )
    identity = _analysis_identity("analysis-request-reservation")
    try:
        manager.spawn_engine(identity)

        owns_admission = await manager.await_engine_request_admission(identity)

        assert owns_admission is False
        key = manager._key(identity)
        with manager._capacity_changed:
            assert manager._request_reservations[key] == 1

        manager.release_engine_request(identity)

        with manager._capacity_changed:
            assert key not in manager._request_reservations
            assert manager._find_idle_engine_locked()[0] == key
    finally:
        manager.shutdown_all()


def test_docker_reconciliation_is_not_run_on_every_idle_reap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_idle_ttl_seconds", 0)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    calls = 0
    elapsed = 0.0

    class _StopAfterReapIntervals:
        waits = 0

        def wait(self, interval: float) -> bool:
            nonlocal elapsed
            self.waits += 1
            elapsed += interval
            return self.waits > 12

        def set(self) -> None:
            return None

    try:
        manager._idle_reap_interval_seconds = 5
        manager._reaper_stop = _StopAfterReapIntervals()
        manager._uses_docker_runtime = True
        manager._reconcile_docker_containers = True
        monkeypatch.setattr(manager, "_reap_idle_engines_once", lambda: None)
        monkeypatch.setattr("runtime.compute_manager.time", SimpleNamespace(monotonic=lambda: elapsed))

        def reconcile(**_kwargs) -> int:
            nonlocal calls
            calls += 1
            return 0

        monkeypatch.setattr("runtime.compute_manager.reconcile_deployment_containers", reconcile)
        manager._reap_idle_engines_loop()

        assert calls == 1
        assert elapsed == 65
    finally:
        manager.shutdown_all()


def test_process_manager_cancels_exact_shared_engine_job_without_stopping_worker() -> None:
    engine = _FakeEngine("analysis-preview-disconnect")
    manager = ProcessManager(engine_factory=lambda _identity, _resource_config: cast(Any, engine))
    identity = _analysis_identity("analysis-preview-disconnect")
    try:
        manager.spawn_engine(identity)
        assert manager.cancel_engine_job(identity, job_id="") is False
        assert manager.cancel_engine_job(identity, job_id="stale-request-42") is True
        assert engine.cancelled_jobs == ["stale-request-42"]
        assert manager.get_engine(identity) is engine
        assert engine.is_process_alive()
    finally:
        manager.shutdown_all()


def test_process_manager_does_not_reap_engine_with_request_reservation(monkeypatch) -> None:
    """An admitted request protects a reused engine until its runner releases it."""
    monkeypatch.setattr(settings, "engine_idle_ttl_seconds", 0)
    monkeypatch.setattr(settings, "engine_idle_reap_interval_seconds", 3600)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-reaper-request-reservation")
    try:
        engine = manager.spawn_engine(identity).engine
        manager.reserve_engine_request(identity)

        manager._reap_idle_engines_once()

        assert manager.get_engine(identity) is engine
        assert engine.is_process_alive()

        manager.release_engine_request(identity)
        manager._reap_idle_engines_once()

        assert manager.get_engine(identity) is None
        assert not engine.is_process_alive()
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


def test_process_manager_starts_distinct_engines_concurrently(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 2)
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
    monkeypatch.setattr(settings, "compute_workers", 1)
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


def test_stopping_engine_keeps_its_compute_capacity_until_shutdown_finishes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    shutdown_entered = threading.Event()
    finish_shutdown = threading.Event()

    class BlockingShutdownEngine(_FakeEngine):
        def shutdown(self) -> None:
            shutdown_entered.set()
            assert finish_shutdown.wait(timeout=2)
            super().shutdown()

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, BlockingShutdownEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-stopping-capacity")
    second_identity = _analysis_identity("analysis-after-stop")
    manager.spawn_engine(first_identity)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            shutdown = executor.submit(manager.shutdown_engine, first_identity)
            assert shutdown_entered.wait(timeout=2)
            with manager._capacity_changed:
                assert manager._capacity_used_locked() == 1
            with pytest.raises(EngineCapacityFull):
                manager.spawn_engine(second_identity)

            finish_shutdown.set()
            shutdown.result(timeout=2)
        assert manager.spawn_engine(second_identity).engine.is_process_alive()
    finally:
        finish_shutdown.set()
        manager.shutdown_all()


def test_releasing_eviction_admission_restores_live_engine(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-live-eviction")
    second_identity = _analysis_identity("analysis-cancelled-eviction")

    try:
        first_engine = manager.spawn_engine(first_identity).engine
        assert asyncio.run(manager.await_spawn_admission(second_identity)) is True

        manager.release_spawn_admission(second_identity, owned=True)

        assert manager.get_engine(first_identity) is first_engine
    finally:
        manager.shutdown_all()


def test_cancelled_eviction_holds_capacity_until_live_engine_is_restored(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))

    current_identity = _analysis_identity("analysis-cancelled-eviction-current")
    cancelled_identity = _analysis_identity("analysis-cancelled-eviction-next")
    racing_identity = _analysis_identity("analysis-cancelled-eviction-racer")
    probe_started = threading.Event()
    allow_probe = threading.Event()
    try:
        current_engine = manager.spawn_engine(current_identity).engine
        assert asyncio.run(manager.await_spawn_admission(cancelled_identity)) is True

        original_probe = current_engine.is_process_alive

        def blocking_probe() -> bool:
            probe_started.set()
            assert allow_probe.wait(timeout=2)
            return original_probe()

        current_engine.is_process_alive = blocking_probe
        with ThreadPoolExecutor(max_workers=1) as executor:
            release = executor.submit(manager.release_spawn_admission, cancelled_identity, owned=True)
            assert probe_started.wait(timeout=1)

            with pytest.raises(EngineCapacityFull):
                manager.spawn_engine(racing_identity)

            allow_probe.set()
            assert release.result(timeout=2) is True

        assert manager.get_engine(current_identity) is current_engine
        assert manager._capacity_starts == 0
    finally:
        allow_probe.set()
        manager.shutdown_all()


def test_process_manager_defers_while_engine_is_reserved(monkeypatch) -> None:
    """Reservations block eviction; spawn raises so the runner can leave the pool."""
    monkeypatch.setattr(settings, "compute_workers", 1)
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


def test_lease_loss_keeps_shared_engine_for_reuse() -> None:
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-shared-lease-loss")
    try:
        engine = manager.spawn_engine(identity).engine
        manager.reserve_engine_request(identity)
        manager.reserve_engine_request(identity)

        assert manager.shutdown_engine_after_request_lease_loss(identity) is False
        assert manager.get_engine(identity) is engine
        assert engine.is_process_alive()

        manager.release_engine_request(identity)
        assert manager.shutdown_engine_after_request_lease_loss(identity) is False
        assert manager.get_engine(identity) is engine
        assert engine.is_process_alive()
    finally:
        manager.shutdown_all()


def test_lease_loss_releases_exclusive_engine_after_last_request() -> None:
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_BUILD,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
        build_id="build-exclusive-lease-loss",
        resource_id="build-exclusive-lease-loss",
    )
    try:
        engine = manager.spawn_engine(identity).engine
        manager.reserve_engine_request(identity)

        assert manager.shutdown_engine_after_request_lease_loss(identity) is True
        assert manager.get_engine(identity) is None
        assert not engine.is_process_alive()
    finally:
        manager.shutdown_all()


def test_lease_loss_does_not_shutdown_engine_with_active_job() -> None:
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-active-job-lease-loss")
    try:
        engine = manager.spawn_engine(identity).engine
        manager.reserve_engine_request(identity)
        engine.current_job_id = "job-1"

        assert manager.shutdown_engine_after_request_lease_loss(identity) is False
        assert manager.get_engine(identity) is not None
        assert engine.is_process_alive()
    finally:
        manager.shutdown_all()


def test_lease_loss_does_not_shutdown_idle_engine_before_reaper(monkeypatch) -> None:
    monkeypatch.setattr(settings, "engine_idle_ttl_seconds", 60)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-idle-lease-loss")
    try:
        engine = manager.spawn_engine(identity).engine

        assert manager.shutdown_engine_after_request_lease_loss(identity) is False
        assert manager.get_engine(identity) is engine
        assert engine.is_process_alive()
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_admitted_reused_engine_is_not_evicted_before_execution(monkeypatch) -> None:
    """An admitted request keeps its existing engine alive until its runner starts."""
    monkeypatch.setattr(settings, "compute_workers", 1)
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
    monkeypatch.setattr(settings, "compute_workers", 1)
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
async def test_process_manager_wait_for_capacity_times_out_without_leaking_waiter(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-capacity-timeout")
    try:
        manager.spawn_engine(first_identity)
        manager.reserve_engine_request(first_identity)

        assert await manager.wait_for_capacity(timeout_seconds=0.01) is False
        assert manager._capacity_waiters == []
    finally:
        manager.release_engine_request(first_identity)
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_capacity_wait_rechecks_after_spurious_wakeup(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-capacity-spurious-wakeup")
    try:
        with manager.acquire_engine(identity):
            waiter = asyncio.create_task(manager.wait_for_capacity(timeout_seconds=1))
            await asyncio.sleep(0.01)
            manager.notify_capacity_changed()
            await asyncio.sleep(0.01)
            assert not waiter.done()

        assert await asyncio.wait_for(waiter, timeout=1)
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_capacity_admission_is_fifo(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
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
    monkeypatch.setattr(settings, "compute_workers", 1)
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
async def test_process_manager_admission_round_robins_builds_under_interactive_load(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    running = _analysis_identity("analysis-fair-running")
    lifecycle = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_BUILD,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_EXCLUSIVE,
        build_id="build-fair",
        resource_id="build-fair",
    )
    interactive_one = _analysis_identity("analysis-fair-one")
    interactive_two = _analysis_identity("analysis-fair-two")
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
        active = manager.spawn_engine(running)
        active.engine.current_job_id = "active-job"
        lifecycle_task = asyncio.create_task(admit_spawn_stop(lifecycle, ENGINE_ADMISSION_PRIORITY_LIFECYCLE))
        first_task = asyncio.create_task(admit_spawn_stop(interactive_one, ENGINE_ADMISSION_PRIORITY_INTERACTIVE))
        second_task = asyncio.create_task(admit_spawn_stop(interactive_two, ENGINE_ADMISSION_PRIORITY_INTERACTIVE))
        await asyncio.sleep(0.05)
        await asyncio.to_thread(manager.shutdown_engine, running)
        await asyncio.wait_for(asyncio.gather(lifecycle_task, first_task, second_task), timeout=2)

        assert order == ["analysis-fair-one", "build-fair", "analysis-fair-two"]
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_reuse_admission_reserves_identity_atomically(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-reserved-reuse")
    competing = _analysis_identity("analysis-reserved-competitor")

    try:
        manager.spawn_engine(identity)
        owns_admission = await manager.await_engine_request_admission(identity)
        assert owns_admission is False

        waiter = asyncio.create_task(manager.await_spawn_admission(competing))
        await asyncio.sleep(0.05)
        assert not waiter.done()

        manager.release_engine_request(identity)
        assert await asyncio.wait_for(waiter, timeout=1) is True
        manager.release_spawn_admission(competing, owned=True)
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_after_resolution", [False, True])
async def test_queued_reuse_admission_owns_its_request_reservation(monkeypatch, cancel_after_resolution: bool) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_target=0,
    )
    identity = _analysis_identity("analysis-queued-reuse-reservation")
    engine = _FakeEngine(identity.resource_id)
    engine.start()
    key = manager._key(identity)
    with manager._capacity_changed:
        manager._capacity_starts = 1

    waiter = asyncio.create_task(manager.await_engine_request_admission(identity))
    try:
        for _ in range(20):
            with manager._capacity_changed:
                if manager._spawn_waiters:
                    break
            await asyncio.sleep(0)
        with manager._capacity_changed:
            assert len(manager._spawn_waiters) == 1
            manager._capacity_starts = 0
            manager._engines[key] = EngineInfo(engine)
            manager._engine_identities[key] = identity
            manager._admit_spawn_waiters_locked()

        if cancel_after_resolution:
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert manager._request_reservations.get(key, 0) == 0
        else:
            assert await asyncio.wait_for(waiter, timeout=1) is False
            assert manager._request_reservations.get(key, 0) == 1
            manager.release_engine_request(identity)
            assert manager._request_reservations.get(key, 0) == 0
    finally:
        if not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_serializes_commands_per_exact_engine_identity(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 2)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    first_identity = _analysis_identity("analysis-single-job")
    second_identity = _analysis_identity("analysis-single-job")
    other_identity = _analysis_identity("analysis-independent-job")
    await manager.await_engine_job_slot(first_identity)
    second = asyncio.create_task(manager.await_engine_job_slot(second_identity))
    try:
        await asyncio.sleep(0)
        assert not second.done()
        await manager.await_engine_job_slot(other_identity)
        manager.release_engine_job_slot(other_identity)
    finally:
        manager.release_engine_job_slot(first_identity)

    await asyncio.wait_for(second, timeout=1)
    manager.release_engine_job_slot(second_identity)
    assert manager._engine_job_slots == {}
    manager.shutdown_all()


@pytest.mark.asyncio
async def test_cancelling_waiting_engine_job_does_not_strand_its_lane(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-job-slot-cancellation")
    await manager.await_engine_job_slot(identity)
    cancelled = asyncio.create_task(manager.await_engine_job_slot(identity))
    next_waiter: asyncio.Task[None] | None = None
    try:
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled

        next_waiter = asyncio.create_task(manager.await_engine_job_slot(identity))
        await asyncio.sleep(0)
        assert not next_waiter.done()
        manager.release_engine_job_slot(identity)
        await asyncio.wait_for(next_waiter, timeout=1)
        manager.release_engine_job_slot(identity)
        assert manager._engine_job_slots == {}
    finally:
        if not cancelled.done():
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)
        if next_waiter is not None and not next_waiter.done():
            next_waiter.cancel()
            await asyncio.gather(next_waiter, return_exceptions=True)
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_process_manager_shutdown_rejects_capacity_waiter(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)))
    running = manager.spawn_engine(_analysis_identity("analysis-running"))
    running.engine.current_job_id = "job-running"
    waiter = asyncio.create_task(manager.await_spawn_admission(_analysis_identity("analysis-waiting")))
    await asyncio.sleep(0.02)

    await asyncio.to_thread(manager.shutdown_all)

    with pytest.raises(RuntimeError, match="shut down"):
        await asyncio.wait_for(waiter, timeout=1)


def test_shutdown_waits_for_engine_start_and_stops_its_registration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 0)
    start_entered = threading.Event()
    finish_start = threading.Event()
    spawn_finished = threading.Event()
    shutdown_finished = threading.Event()
    spawn_errors: list[BaseException] = []
    created: list[_FakeEngine] = []

    class BlockingStartEngine(_FakeEngine):
        def start(self) -> None:
            start_entered.set()
            assert finish_start.wait(timeout=2)
            super().start()

    def factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None = None) -> _FakeEngine:
        engine = BlockingStartEngine(identity.resource_id, resource_config)
        created.append(engine)
        return engine

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, factory(identity, resource_config)), warm_worker_target=0)
    identity = _analysis_identity("analysis-shutdown-during-start")

    def spawn() -> None:
        try:
            manager.spawn_engine(identity)
        except BaseException as exc:
            spawn_errors.append(exc)
        finally:
            spawn_finished.set()

    def shutdown() -> None:
        try:
            manager.shutdown_all()
        finally:
            shutdown_finished.set()

    spawn_thread = threading.Thread(target=spawn, name="test-engine-start")
    shutdown_thread = threading.Thread(target=shutdown, name="test-engine-shutdown")
    try:
        spawn_thread.start()
        assert start_entered.wait(timeout=1)
        shutdown_thread.start()
        with manager._capacity_changed:
            assert manager._capacity_changed.wait_for(lambda: manager._closed, timeout=1)

        assert not shutdown_finished.is_set()
        finish_start.set()
        assert spawn_finished.wait(timeout=2)
        assert shutdown_finished.wait(timeout=2)
        spawn_thread.join(timeout=1)
        shutdown_thread.join(timeout=1)

        assert spawn_errors == []
        assert manager.get_engine(identity) is None
        assert not manager._starting_engines
        assert len(created) == 1
        assert not created[0].is_process_alive()
    finally:
        finish_start.set()
        if spawn_thread.is_alive():
            spawn_thread.join(timeout=2)
        if shutdown_thread.is_alive():
            shutdown_thread.join(timeout=2)
        if not shutdown_finished.is_set():
            manager.shutdown_all()


@pytest.mark.asyncio
async def test_same_identity_waiters_park_until_one_engine_start_finishes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    start_entered = threading.Event()
    release_start = threading.Event()
    created: list[_FakeEngine] = []

    class BlockingStartEngine(_FakeEngine):
        def start(self) -> None:
            start_entered.set()
            assert release_start.wait(timeout=2)
            super().start()

    def factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None = None):
        engine = BlockingStartEngine(identity.resource_id, resource_config)
        created.append(engine)
        return cast(Any, engine)

    manager = ProcessManager(engine_factory=factory)
    identity = _analysis_identity("analysis-shared-admission")

    async def start_once() -> None:
        owns_admission = await manager.await_spawn_admission(identity)
        try:
            await asyncio.to_thread(manager.spawn_engine, identity)
        finally:
            manager.release_spawn_admission(identity, owned=owns_admission)

    try:
        leader = asyncio.create_task(start_once())
        assert await asyncio.wait_for(asyncio.to_thread(start_entered.wait, 1), timeout=2)
        followers = [asyncio.create_task(manager.await_spawn_admission(identity)) for _ in range(50)]
        await asyncio.sleep(0.05)

        assert all(not follower.done() for follower in followers)
        assert len(manager._capacity_waiters) == 50
        assert len(created) == 1

        release_start.set()
        await asyncio.wait_for(leader, timeout=2)
        results = await asyncio.wait_for(asyncio.gather(*followers), timeout=2)

        assert results == [False] * 50
        assert manager.get_engine(identity) is created[0]
        assert len(created) == 1
    finally:
        release_start.set()
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_cancelled_request_does_not_release_runner_owned_admission(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    monkeypatch.setattr(settings, "compute_warm_workers", 0)
    start_entered = threading.Event()
    release_start = threading.Event()

    class BlockingStartEngine(_FakeEngine):
        def start(self) -> None:
            start_entered.set()
            assert release_start.wait(timeout=2)
            super().start()

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, BlockingStartEngine(identity.resource_id, resource_config)))
    identity = _analysis_identity("analysis-cancelled-request")
    owns_admission = await manager.await_spawn_admission(identity)
    assert owns_admission is True

    async def request() -> None:
        try:
            await asyncio.to_thread(manager.spawn_engine, identity)
        finally:
            manager.release_spawn_admission(identity, owned=owns_admission)

    task = asyncio.create_task(request())
    try:
        assert await asyncio.wait_for(asyncio.to_thread(start_entered.wait, 1), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        with manager._capacity_changed:
            assert manager._capacity_starts == 1
            assert manager._cold_starts == 1

        release_start.set()
        deadline = time.monotonic() + 2
        while manager.get_engine(identity) is None and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert manager.get_engine(identity) is not None
        with manager._capacity_changed:
            assert manager._capacity_starts == 0
            assert manager._cold_starts == 0
    finally:
        release_start.set()
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_cold_engine_start_fanout_is_bounded_by_compute_workers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 8)
    monkeypatch.setattr(settings, "compute_warm_workers", 0)
    loop = asyncio.get_running_loop()
    starts_entered = asyncio.Event()
    release_starts = threading.Event()
    lock = threading.Lock()
    active_starts = 0
    peak_starts = 0
    start_count = 0
    start_limit = settings.compute_workers

    class BlockingStartEngine(_FakeEngine):
        def start(self) -> None:
            nonlocal active_starts, peak_starts, start_count
            with lock:
                active_starts += 1
                start_count += 1
                peak_starts = max(peak_starts, active_starts)
                if active_starts == start_limit:
                    loop.call_soon_threadsafe(starts_entered.set)
            assert release_starts.wait(timeout=2)
            try:
                super().start()
            finally:
                with lock:
                    active_starts -= 1

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, BlockingStartEngine(identity.resource_id, resource_config)))
    identities = [_analysis_identity(f"analysis-cold-limit-{index}") for index in range(10)]

    async def spawn(identity: compute_pb2.EngineIdentity) -> None:
        owns_admission = await manager.await_spawn_admission(identity)
        try:
            await asyncio.to_thread(manager.spawn_engine, identity)
        finally:
            manager.release_spawn_admission(identity, owned=owns_admission)

    tasks = [asyncio.create_task(spawn(identity)) for identity in identities]
    try:
        await asyncio.wait_for(starts_entered.wait(), timeout=5)
        with manager._capacity_changed:
            assert manager._cold_starts == start_limit
            assert len(manager._engine_events) == start_limit
            assert manager._capacity_starts == start_limit
            assert len(manager._spawn_waiters) == len(identities) - start_limit

        release_starts.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        assert start_count == len(identities)
        assert peak_starts == start_limit
        assert manager._cold_starts == 0
        # All starts completed, but idle identities beyond the active worker
        # budget are expected to be evicted as the queued starts are admitted.
        registered_identities = [identity for identity in identities if manager.get_engine(identity) is not None]
        assert len(registered_identities) == 8
        assert len(registered_identities) < len(identities)
    finally:
        release_starts.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_warm_and_assigned_starts_use_independent_budgets(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 8)
    monkeypatch.setattr(settings, "compute_warm_workers", 1)
    loop = asyncio.get_running_loop()
    starts_entered = asyncio.Event()
    release_starts = threading.Event()
    lock = threading.Lock()
    active_starts = 0
    peak_starts = 0

    def block_start() -> None:
        nonlocal active_starts, peak_starts
        with lock:
            active_starts += 1
            peak_starts = max(peak_starts, active_starts)
            if active_starts == 4:
                loop.call_soon_threadsafe(starts_entered.set)
        try:
            assert release_starts.wait(timeout=2)
        finally:
            with lock:
                active_starts -= 1

    class BlockingEngine(_FakeEngine):
        def start(self) -> None:
            block_start()
            super().start()

    class BlockingWarmWorker(_FakeWarmWorker):
        def start(self) -> None:
            block_start()
            super().start()

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, BlockingEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: cast(ComputeEngine, BlockingWarmWorker()),
    )
    identities = [_analysis_identity(f"analysis-warm-start-budget-{index}") for index in range(3)]

    async def spawn(identity: compute_pb2.EngineIdentity) -> None:
        owns_admission = await manager.await_spawn_admission(identity)
        try:
            await asyncio.to_thread(manager.spawn_engine, identity)
        finally:
            manager.release_spawn_admission(identity, owned=owns_admission)

    tasks = [asyncio.create_task(spawn(identity)) for identity in identities]
    try:
        await asyncio.wait_for(starts_entered.wait(), timeout=5)
        with manager._capacity_changed:
            assert manager._cold_starts == 4
            assert manager._warm_worker_starts == 1
            assert manager._capacity_starts == 3
            assert len(manager._spawn_waiters) == 0

        release_starts.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
        assert await asyncio.to_thread(manager.wait_for_warm_workers_ready, timeout_seconds=2)

        assert peak_starts == 4
        with manager._capacity_changed:
            assert manager._cold_starts == 0
        assert all(manager.get_engine(identity) is not None for identity in identities)
    finally:
        release_starts.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_failed_cold_start_releases_its_shared_capacity(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    failed_identity = _analysis_identity("analysis-cold-failure")
    next_identity = _analysis_identity("analysis-after-cold-failure")

    class FailingStartEngine(_FakeEngine):
        def start(self) -> None:
            if self.analysis_id == failed_identity.resource_id:
                raise RuntimeError("simulated start failure")
            super().start()

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, FailingStartEngine(identity.resource_id, resource_config)))
    try:
        failed_admission = await manager.await_spawn_admission(failed_identity)
        next_admission = asyncio.create_task(manager.await_spawn_admission(next_identity))
        await asyncio.sleep(0.02)
        assert not next_admission.done()

        with pytest.raises(RuntimeError, match="simulated start failure"):
            await asyncio.to_thread(manager.spawn_engine, failed_identity)
        manager.release_spawn_admission(failed_identity, owned=failed_admission)

        assert await asyncio.wait_for(next_admission, timeout=1) is True
        assert manager._cold_starts == 1
        await asyncio.to_thread(manager.spawn_engine, next_identity)
        manager.release_spawn_admission(next_identity, owned=True)
        assert manager._cold_starts == 0
    finally:
        if not next_admission.done():
            next_admission.cancel()
        await asyncio.gather(next_admission, return_exceptions=True)
        manager.shutdown_all()


class _FakeWarmWorker(_FakeEngine):
    def __init__(self, resource_id: str = "", resource_config: dict | None = None) -> None:
        super().__init__(resource_id, resource_config)
        self.bound_identities: list[compute_pb2.EngineIdentity] = []
        self._is_warm_worker = not bool(resource_id)

    def bind_identity(self, identity: compute_pb2.EngineIdentity, *, resource_config: dict | None = None, namespace: str | None = None) -> None:
        self.analysis_id = identity.resource_id
        self.bound_identities.append(identity)
        self._is_warm_worker = False

    @property
    def is_warm_worker(self) -> bool:
        return self._is_warm_worker


def test_process_manager_warm_workers_replenishes_and_claims(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 2)
    monkeypatch.setattr(settings, "compute_workers", 3)

    created_warm: list[_FakeWarmWorker] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmWorker()
        created_warm.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=warm_factory,
    )

    try:
        # Wait for the warm-worker reserve to reach its target.
        for _ in range(50):
            if len(manager._warm_workers) == 2:
                break
            time.sleep(0.02)
        assert len(manager._warm_workers) == 2
        assert len(created_warm) == 2
        assert all(w.is_process_alive() for w in created_warm)

        # Spawn engine 1 -> it should be assigned a warm worker.
        id1 = _analysis_identity("analysis-claimed-1")
        info1 = manager.spawn_engine(id1)
        claimed_engine = cast(_FakeWarmWorker, info1.engine)
        assert claimed_engine in created_warm
        assert claimed_engine.bound_identities == [id1]
        assert not claimed_engine.is_warm_worker

        # Replenisher should create 1 more warm worker to get back to 2. Warm
        # The warm-worker reserve is separate from active worker capacity.
        for _ in range(50):
            if len(manager._warm_workers) == 2 and len(created_warm) == 3:
                break
            time.sleep(0.02)
        assert len(manager._warm_workers) == 2
        assert len(created_warm) == 3

        # Spawn engine 2 -> claims another warm worker.
        id2 = _analysis_identity("analysis-claimed-2")
        info2 = manager.spawn_engine(id2)
        assert cast(_FakeWarmWorker, info2.engine) in created_warm

        # The replacement is started even though the two active engines have
        # filled the configured active capacity.
        for _ in range(50):
            if len(manager._warm_workers) == 2 and len(created_warm) == 4:
                break
            time.sleep(0.02)
        assert len(manager._warm_workers) == 2
        assert len(created_warm) == 4
        with manager._capacity_changed:
            assert manager._capacity_used_locked() == 2
    finally:
        manager.shutdown_all()
        assert all(not w.is_process_alive() for w in created_warm)


def test_warm_reserve_is_independent_of_active_compute_budget(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    monkeypatch.setattr(settings, "compute_warm_workers", 2)
    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: cast(ComputeEngine, _FakeWarmWorker()),
    )

    try:
        assert manager.wait_for_warm_workers_ready(timeout_seconds=2)
        assert manager.warm_worker_count == 2
        with manager._capacity_changed:
            assert manager._capacity_used_locked() == 0
            assert manager._capacity_starts == 0
    finally:
        manager.shutdown_all()


def test_warm_workers_start_is_reserved_while_docker_boots(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 1)
    monkeypatch.setattr(settings, "compute_workers", 2)
    started = threading.Event()
    release = threading.Event()

    def warm_factory() -> ComputeEngine:
        started.set()
        assert release.wait(1)
        return cast(ComputeEngine, _FakeWarmWorker())

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=warm_factory,
    )

    try:
        assert started.wait(1)
        with manager._capacity_changed:
            assert manager._warm_worker_starts == 1
            assert len(manager._warm_workers) + manager._warm_worker_starts == 1
        release.set()
        assert manager.wait_for_warm_workers_ready(timeout_seconds=1)
    finally:
        release.set()
        manager.shutdown_all()


def test_shutdown_waits_for_inflight_warm_worker_start(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 1)
    monkeypatch.setattr(settings, "compute_workers", 2)
    start_entered = threading.Event()
    finish_start = threading.Event()
    shutdown_finished = threading.Event()
    shutdown_errors: list[BaseException] = []

    class BlockingWarmWorker(_FakeWarmWorker):
        def start(self) -> None:
            start_entered.set()
            assert finish_start.wait(timeout=2)
            super().start()

    warm_worker = BlockingWarmWorker()
    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: cast(ComputeEngine, warm_worker),
    )

    def shutdown() -> None:
        try:
            manager.shutdown_all()
        except BaseException as exc:
            shutdown_errors.append(exc)
        finally:
            shutdown_finished.set()

    shutdown_thread = threading.Thread(target=shutdown, name="test-manager-shutdown")
    try:
        assert start_entered.wait(timeout=1)
        shutdown_thread.start()
        with manager._capacity_changed:
            assert manager._capacity_changed.wait_for(lambda: manager._closed, timeout=1)

        assert shutdown_thread.is_alive()
        with pytest.raises(RuntimeError, match="Process manager is shut down"):
            manager.spawn_engine(_analysis_identity("analysis-during-shutdown"))

        finish_start.set()
        assert shutdown_finished.wait(timeout=2)
        shutdown_thread.join(timeout=1)
        assert not shutdown_thread.is_alive()
        assert shutdown_errors == []
        assert manager.warm_worker_count == 0
        assert not warm_worker.is_process_alive()
    finally:
        finish_start.set()
        if shutdown_thread.is_alive():
            shutdown_thread.join(timeout=2)
        if not shutdown_finished.is_set():
            manager.shutdown_all()


def test_process_manager_replenishes_after_unhealthy_warm_claim(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 2)
    monkeypatch.setattr(settings, "compute_workers", 3)

    created_warm: list[_FakeWarmWorker] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmWorker()
        created_warm.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=warm_factory,
    )

    try:
        for _ in range(50):
            if len(manager._warm_workers) == 2:
                break
            time.sleep(0.02)
        assert len(manager._warm_workers) == 2

        # Both reserved candidates can fail health after admission. The active
        # request must still complete, and the warm-worker reserve must recover to its
        # configured size rather than waiting for a later claim to wake it.
        for candidate in tuple(created_warm):
            monkeypatch.setattr(candidate, "check_health", lambda: False)

        manager.spawn_engine(_analysis_identity("analysis-unhealthy-warm-claim"))

        for _ in range(100):
            if len(manager._warm_workers) == 2 and len(created_warm) > 2:
                break
            time.sleep(0.02)
        assert len(manager._warm_workers) == 2
        assert len(created_warm) > 2
    finally:
        manager.shutdown_all()
        assert all(not warm.is_process_alive() for warm in created_warm)


def test_process_manager_waits_for_initial_warm_workers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 2)
    monkeypatch.setattr(settings, "compute_workers", 2)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: cast(ComputeEngine, _FakeWarmWorker()),
    )
    try:
        assert manager.wait_for_warm_workers_ready(timeout_seconds=1.0)
        assert len(manager._warm_workers) == 2
    finally:
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_warm_workers_admission_reserves_each_engine_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 2)
    monkeypatch.setattr(settings, "compute_workers", 2)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: cast(ComputeEngine, _FakeWarmWorker()),
    )
    identities = [_analysis_identity(f"analysis-warm-admission-{index}") for index in range(3)]
    tasks: list[asyncio.Task[bool]] = []
    try:
        assert manager.wait_for_warm_workers_ready(timeout_seconds=1.0)
        tasks = [asyncio.create_task(manager.await_spawn_admission(identity)) for identity in identities]
        await asyncio.sleep(0.05)

        # Two warm workers can be admitted, but the third must remain queued
        # until one of those claims is released. The old boolean reservation
        # check admitted all three before any spawn popped a worker.
        admitted = [task for task in tasks if task.done() and not task.cancelled()]
        assert len(admitted) == 2
        assert all(task.result() is True for task in admitted)
        with manager._capacity_changed:
            assert manager._capacity_used_locked() <= settings.compute_workers
            assert manager._warm_worker_claims == 2

        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for identity, task in zip(identities, tasks, strict=True):
            if task.done() and not task.cancelled() and task.exception() is None and task.result():
                manager.release_spawn_admission(identity, owned=True)
        with manager._capacity_changed:
            assert manager._capacity_used_locked() == 0
            assert manager._warm_worker_claims == 0
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        manager.shutdown_all()


@pytest.mark.asyncio
async def test_warm_workers_replenishes_while_spawn_waiter_is_parked(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 1)
    monkeypatch.setattr(settings, "compute_workers", 2)

    created_warm: list[_FakeWarmWorker] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmWorker()
        created_warm.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=warm_factory,
    )
    parked_admission: asyncio.Task[bool] | None = None
    try:
        assert manager.wait_for_warm_workers_ready(timeout_seconds=1)
        first_identity = _analysis_identity("analysis-busy")
        first_info = manager.spawn_engine(first_identity)
        for _ in range(100):
            if len(manager._warm_workers) == 1:
                break
            await asyncio.sleep(0.01)
        assert len(manager._warm_workers) == 1

        # Keep the first engine non-evictable. Reserve the remaining active
        # slot with a warm claim, then park a third identity behind capacity.
        with manager._capacity_changed:
            first_info.active_reservations = 1
        second_identity = _analysis_identity("analysis-warm-claim")
        assert await manager.await_spawn_admission(second_identity)

        parked_identity = _analysis_identity("analysis-parked")
        parked_admission = asyncio.create_task(manager.await_spawn_admission(parked_identity))
        for _ in range(100):
            with manager._capacity_changed:
                if any(waiter.key == manager._key(parked_identity) for waiter in manager._spawn_waiters):
                    break
            await asyncio.sleep(0.01)
        with manager._capacity_changed:
            assert any(waiter.key == manager._key(parked_identity) for waiter in manager._spawn_waiters)

        await asyncio.to_thread(manager.spawn_engine, second_identity, _reserve=True)

        # Refill remains independent of active admission pressure. The parked
        # request must stay parked because both active engines are occupied.
        for _ in range(100):
            if len(manager._warm_workers) == 1:
                break
            await asyncio.sleep(0.01)
        assert len(manager._warm_workers) == 1
        assert len(created_warm) == 3
        assert not parked_admission.done()
    finally:
        if parked_admission is not None and not parked_admission.done():
            parked_admission.cancel()
            await asyncio.gather(parked_admission, return_exceptions=True)
        manager.shutdown_all()


def test_process_manager_warm_workers_readiness_has_a_bounded_timeout(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 1)
    monkeypatch.setattr(settings, "compute_workers", 1)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: (_ for _ in ()).throw(RuntimeError("engine unavailable")),
    )
    try:
        started = time.monotonic()
        assert not manager.wait_for_warm_workers_ready(timeout_seconds=0.05)
        assert time.monotonic() - started < 1.0
    finally:
        manager.shutdown_all()


def test_process_manager_can_disable_warm_workers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 2)
    created_warm: list[_FakeWarmWorker] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmWorker()
        created_warm.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=warm_factory,
        warm_worker_target=0,
    )

    try:
        time.sleep(0.05)
        assert len(manager._warm_workers) == 0
        assert created_warm == []
        assert manager._warm_worker_replenisher_thread is None
    finally:
        manager.shutdown_all()


def test_capacity_decisions_never_probe_the_engine_runtime(monkeypatch) -> None:
    """Capacity scans run under the engines lock, so they must not do engine I/O.

    A container inspection or engine RPC can hang for as long as a container
    boot takes. When a capacity scan performs one, every claim, release and
    status call in the worker queues behind it.
    """
    monkeypatch.setattr(settings, "compute_workers", 1)
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
    monkeypatch.setattr(settings, "compute_workers", 1)
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


@pytest.mark.parametrize("capacity", [1, 2])
@pytest.mark.parametrize("restart_mode", ["dead", "reconfigured", "configure"])
def test_engine_restart_transfers_its_capacity_once(monkeypatch, capacity: int, restart_mode: str) -> None:
    monkeypatch.setattr(settings, "compute_workers", capacity)
    monkeypatch.setattr(settings, "compute_warm_workers", 0)
    created: list[_FakeEngine] = []

    def factory(identity: compute_pb2.EngineIdentity, resource_config: dict | None) -> _FakeEngine:
        engine = _FakeEngine(identity.resource_id, resource_config)
        created.append(engine)
        return engine

    manager = ProcessManager(engine_factory=lambda identity, resource_config: cast(Any, factory(identity, resource_config)))
    identity = _analysis_identity("analysis-restart-after-failure")
    try:
        first = manager.spawn_engine(identity, resource_config={"max_memory_mb": 1234})
        replacement_config = {"max_memory_mb": 1234}
        if restart_mode == "dead":
            cast(Any, first.engine)._alive = False
        else:
            replacement_config = {"max_memory_mb": 5678}

        if restart_mode == "configure":
            second = manager.restart_engine_with_config(identity, replacement_config)
        else:
            second = manager.spawn_engine(identity, resource_config=replacement_config)

        assert second.engine is not first.engine
        assert len(created) == 2
        assert manager.get_engine(identity) is second.engine
        assert second.engine.resource_config == replacement_config
        with manager._capacity_changed:
            assert manager._capacity_starts == 0
            assert manager._cold_starts == 0
            assert manager._capacity_used_locked() == 1
    finally:
        manager.shutdown_all()


def test_failed_engine_restart_releases_warm_worker_claim(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_workers", 1)
    monkeypatch.setattr(settings, "compute_warm_workers", 1)

    class FailingShutdownWarmWorker(_FakeWarmWorker):
        def shutdown(self) -> None:
            if self.bound_identities:
                raise RuntimeError("simulated stop failure")
            super().shutdown()

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=lambda: cast(ComputeEngine, FailingShutdownWarmWorker()),
    )
    identity = _analysis_identity("analysis-restart-warm-claim")
    try:
        assert manager.wait_for_warm_workers_ready(timeout_seconds=1)
        first = manager.spawn_engine(identity)
        assert manager.warm_worker_count == 0
        deadline = time.monotonic() + 1
        while manager.warm_worker_count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.warm_worker_count == 1

        cast(Any, first.engine)._alive = False
        with pytest.raises(RuntimeError, match="simulated stop failure"):
            manager.spawn_engine(identity)

        with manager._capacity_changed:
            assert manager._warm_worker_claims == 0
            assert manager._capacity_starts == 0
    finally:
        # The simulated identity engine is removed before its failed stop;
        # the warm worker remains independently owned by the manager.
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


def test_warm_workers_reach_configured_reserve_independent_of_compute_capacity(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compute_warm_workers", 4)
    monkeypatch.setattr(settings, "compute_workers", 2)

    created: list[_FakeWarmWorker] = []

    def warm_factory() -> ComputeEngine:
        engine = _FakeWarmWorker()
        created.append(engine)
        return cast(ComputeEngine, engine)

    manager = ProcessManager(
        engine_factory=lambda identity, resource_config: cast(Any, _FakeEngine(identity.resource_id, resource_config)),
        warm_worker_factory=warm_factory,
    )
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(manager._warm_workers) < 4:
            time.sleep(0.02)

        assert len(manager._warm_workers) == 4
        # Warm workers are an additional, ready-but-unassigned reserve. They do
        # not consume active compute slots until bound to an identity.
        time.sleep(0.2)
        assert len(created) == 4
        assert manager._capacity_starts == 0
    finally:
        manager.shutdown_all()
