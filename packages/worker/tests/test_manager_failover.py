from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any, cast

import pytest

from runtime.dispatcher_health import DispatcherHealth
from runtime.manager_lease import WorkerManagerLeaseLost
from runtime.worker_runtime_client import WorkerRuntimeClient


def _load_runtime_process():
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("worker_main_for_failover_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load worker runtime module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_process = _load_runtime_process()


def _health() -> DispatcherHealth:
    return DispatcherHealth("worker-manager:test", lanes=("dispatch",), max_age_seconds=30)


class _Lease:
    def __init__(self, *, acquire_on_attempt: int = 1) -> None:
        self.attempts = 0
        self.acquire_on_attempt = acquire_on_attempt
        self.lost = False
        self.released = 0
        self.checks = 0

    def acquire(self) -> bool:
        self.attempts += 1
        return self.attempts >= self.acquire_on_attempt

    def check(self, *, force: bool = False) -> None:
        del force
        self.checks += 1
        if self.lost:
            raise WorkerManagerLeaseLost("lease connection gone")

    def release(self) -> None:
        self.released += 1


@pytest.mark.asyncio
async def test_standby_waits_until_the_manager_lease_is_free(monkeypatch) -> None:
    monkeypatch.setattr(runtime_process, "_MANAGER_LEASE_RETRY_SECONDS", 0.001)
    lease = _Lease(acquire_on_attempt=3)
    health = _health()

    assert await runtime_process._wait_for_manager_lease(asyncio.Event(), cast(Any, lease), health) is True
    assert lease.attempts == 3
    assert lease.released == 0
    # Docker keeps probing while another machine owns the lease.
    assert health.state == "standby"
    assert health.snapshot()["healthy"] is True


@pytest.mark.asyncio
async def test_a_cold_start_that_wins_the_lease_at_once_is_not_a_standby() -> None:
    lease = _Lease()
    health = _health()
    assert await runtime_process._wait_for_manager_lease(asyncio.Event(), cast(Any, lease), health) is True
    assert health.state == "starting"
    assert health.snapshot()["healthy"] is False


@pytest.mark.asyncio
async def test_standby_releases_a_lease_won_while_stopping(monkeypatch) -> None:
    monkeypatch.setattr(runtime_process, "_MANAGER_LEASE_RETRY_SECONDS", 0.001)
    stop = asyncio.Event()
    lease = _Lease(acquire_on_attempt=2)
    original_acquire = lease.acquire

    def acquire() -> bool:
        acquired = original_acquire()
        if acquired:
            stop.set()
        return acquired

    lease.acquire = acquire  # type: ignore[method-assign]
    assert await runtime_process._wait_for_manager_lease(stop, cast(Any, lease), _health()) is False
    assert lease.released == 1


@pytest.mark.asyncio
async def test_losing_the_lease_stops_the_running_generation_and_returns_to_standby(monkeypatch) -> None:
    monkeypatch.setattr(runtime_process, "_MANAGER_LEASE_CHECK_SECONDS", 0.001)
    monkeypatch.setattr(runtime_process, "reset_docker_host_registry", lambda: None)
    lease = _Lease()
    generation_started = asyncio.Event()
    generation_stopped = asyncio.Event()
    guards: list[Any] = []

    async def wait_for_generation(stop_event: asyncio.Event, _client) -> int | None:
        return None if stop_event.is_set() else 5

    health = _health()
    health.standby()
    states: list[str] = []

    async def run_generation(stop_event: asyncio.Event, _client, generation: int, *, manager_guard=None, health=None) -> None:
        assert generation == 5
        guards.append(manager_guard)
        states.append(health.state)
        generation_started.set()
        await stop_event.wait()
        generation_stopped.set()

    monkeypatch.setattr(runtime_process, "_wait_for_coordinator_generation", wait_for_generation)
    monkeypatch.setattr(runtime_process, "_run_worker_manager_generation", run_generation)

    role = asyncio.create_task(runtime_process._run_as_manager(asyncio.Event(), cast(WorkerRuntimeClient, object()), cast(Any, lease), health))
    await asyncio.wait_for(generation_started.wait(), timeout=1.0)
    # A standby that won the lease answers healthy while it sweeps the hosts
    # and rebuilds the reserve, until it registers with the coordinator.
    assert states == ["taking_over"]
    assert health.snapshot()["healthy"] is True
    lease.lost = True

    assert await asyncio.wait_for(role, timeout=1.0) is True
    assert lease.checks >= 1
    assert generation_stopped.is_set()
    assert guards and guards[0] == lease.check


@pytest.mark.asyncio
async def test_process_stop_ends_the_manager_role_without_losing_the_lease(monkeypatch) -> None:
    monkeypatch.setattr(runtime_process, "_MANAGER_LEASE_CHECK_SECONDS", 0.001)
    monkeypatch.setattr(runtime_process, "reset_docker_host_registry", lambda: None)
    lease = _Lease()
    process_stop = asyncio.Event()

    async def wait_for_generation(stop_event: asyncio.Event, _client) -> int | None:
        return None if stop_event.is_set() else 2

    health = _health()

    async def run_generation(stop_event: asyncio.Event, _client, _generation: int, *, manager_guard=None, health=None) -> None:
        process_stop.set()
        await stop_event.wait()

    monkeypatch.setattr(runtime_process, "_wait_for_coordinator_generation", wait_for_generation)
    monkeypatch.setattr(runtime_process, "_run_worker_manager_generation", run_generation)

    lost = await asyncio.wait_for(
        runtime_process._run_as_manager(process_stop, cast(WorkerRuntimeClient, object()), cast(Any, lease), health),
        timeout=1.0,
    )
    assert lost is False
    # A cold start keeps the strict probe: unhealthy until it registers.
    assert health.state == "starting"


@pytest.mark.asyncio
async def test_a_manager_between_coordinator_generations_stays_healthy(monkeypatch) -> None:
    monkeypatch.setattr(runtime_process, "_MANAGER_LEASE_CHECK_SECONDS", 0.001)
    monkeypatch.setattr(runtime_process, "reset_docker_host_registry", lambda: None)
    lease = _Lease()
    process_stop = asyncio.Event()
    health = _health()
    generations = iter([3, 4])
    states: list[tuple[int, str, bool]] = []

    async def wait_for_generation(stop_event: asyncio.Event, _client) -> int | None:
        return None if stop_event.is_set() else next(generations, None)

    async def run_generation(stop_event: asyncio.Event, _client, generation: int, *, manager_guard=None, health=None) -> None:
        states.append((generation, health.state, bool(health.snapshot()["healthy"])))
        # The cold start registers normally; its generation then ends because
        # the coordinator failed over, which drops the registration.
        health.registered()
        health.progress("dispatch")
        health.registration_changed(False)
        if generation == 4:
            process_stop.set()
            await stop_event.wait()

    monkeypatch.setattr(runtime_process, "_wait_for_coordinator_generation", wait_for_generation)
    monkeypatch.setattr(runtime_process, "_run_worker_manager_generation", run_generation)

    lost = await asyncio.wait_for(
        runtime_process._run_as_manager(process_stop, cast(WorkerRuntimeClient, object()), cast(Any, lease), health),
        timeout=5.0,
    )
    assert lost is False
    # Generation 3 is the cold start (strict probe); generation 4 begins while
    # the coordinator fails over, and the worker stays healthy meanwhile.
    assert states == [(3, "starting", False), (4, "taking_over", True)]


@pytest.mark.asyncio
async def test_generation_guard_proves_the_lease_before_the_coordinator_generation(monkeypatch) -> None:
    order: list[str] = []
    captured: dict[str, Any] = {}

    class Client:
        def assert_coordinator_generation(self, generation: int) -> None:
            order.append(f"coordinator:{generation}")

    async def runtime(stop_event: asyncio.Event, **kwargs) -> None:
        captured["guard"] = kwargs["coordinator_guard"]
        stop_event.set()

    async def monitor(process_stop_event: asyncio.Event, generation_stop_event: asyncio.Event, _client, _generation: int) -> None:
        await generation_stop_event.wait()

    monkeypatch.setattr(runtime_process, "run_worker_manager_runtime", runtime)
    monkeypatch.setattr(runtime_process, "_watch_coordinator_generation", monitor)

    def manager_guard() -> None:
        order.append("lease")

    await runtime_process._run_worker_manager_generation(asyncio.Event(), cast(WorkerRuntimeClient, Client()), 9, manager_guard=manager_guard)
    captured["guard"]()
    assert order == ["lease", "coordinator:9"]

    def lost_lease() -> None:
        raise WorkerManagerLeaseLost("gone")

    order.clear()
    await runtime_process._run_worker_manager_generation(asyncio.Event(), cast(WorkerRuntimeClient, Client()), 9, manager_guard=lost_lease)
    with pytest.raises(WorkerManagerLeaseLost):
        captured["guard"]()
    assert order == []
