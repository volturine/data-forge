from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any, cast

import pytest

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

    assert await runtime_process._wait_for_manager_lease(asyncio.Event(), cast(Any, lease)) is True
    assert lease.attempts == 3
    assert lease.released == 0


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
    assert await runtime_process._wait_for_manager_lease(stop, cast(Any, lease)) is False
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

    async def run_generation(stop_event: asyncio.Event, _client, generation: int, *, manager_guard=None) -> None:
        assert generation == 5
        guards.append(manager_guard)
        generation_started.set()
        await stop_event.wait()
        generation_stopped.set()

    monkeypatch.setattr(runtime_process, "_wait_for_coordinator_generation", wait_for_generation)
    monkeypatch.setattr(runtime_process, "_run_worker_generation", run_generation)

    role = asyncio.create_task(runtime_process._run_as_manager(asyncio.Event(), cast(WorkerRuntimeClient, object()), cast(Any, lease)))
    await asyncio.wait_for(generation_started.wait(), timeout=1.0)
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

    async def run_generation(stop_event: asyncio.Event, _client, _generation: int, *, manager_guard=None) -> None:
        process_stop.set()
        await stop_event.wait()

    monkeypatch.setattr(runtime_process, "_wait_for_coordinator_generation", wait_for_generation)
    monkeypatch.setattr(runtime_process, "_run_worker_generation", run_generation)

    lost = await asyncio.wait_for(
        runtime_process._run_as_manager(process_stop, cast(WorkerRuntimeClient, object()), cast(Any, lease)),
        timeout=1.0,
    )
    assert lost is False


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

    monkeypatch.setattr(runtime_process, "run_runtime_coordinator", runtime)
    monkeypatch.setattr(runtime_process, "_watch_coordinator_generation", monitor)

    def manager_guard() -> None:
        order.append("lease")

    await runtime_process._run_worker_generation(asyncio.Event(), cast(WorkerRuntimeClient, Client()), 9, manager_guard=manager_guard)
    captured["guard"]()
    assert order == ["lease", "coordinator:9"]

    def lost_lease() -> None:
        raise WorkerManagerLeaseLost("gone")

    order.clear()
    await runtime_process._run_worker_generation(asyncio.Event(), cast(WorkerRuntimeClient, Client()), 9, manager_guard=lost_lease)
    with pytest.raises(WorkerManagerLeaseLost):
        captured["guard"]()
    assert order == []
