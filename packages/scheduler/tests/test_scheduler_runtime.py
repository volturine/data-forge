from __future__ import annotations

import asyncio
import os

import pytest

import main as scheduler_main
from scheduler_grpc.health import DispatcherHealth


class FakeSchedulerClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.run_due_calls = 0

    async def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int, retry_seconds: float | None = None) -> None:
        assert hostname
        assert pid == os.getpid()
        assert capacity == 1
        self.calls.append(("register", worker_id))

    async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        self.calls.append(("heartbeat", worker_id))

    async def stop(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
        self.calls.append(("stop", worker_id))

    async def due_schedule_namespaces(self) -> list[scheduler_main.DueScheduleNamespace]:
        self.calls.append(("due_schedule_namespaces", "default"))
        return [scheduler_main.DueScheduleNamespace(namespace="default", generation=1)]

    async def run_due(self, *, worker_id: str, namespace: str, generation: int, wake_ids: tuple[int, ...] = ()) -> scheduler_main.SchedulerRunDueResult:
        assert generation == 1
        self.run_due_calls += 1
        self.calls.append(("run_due", f"{worker_id}:{namespace}"))
        return scheduler_main.SchedulerRunDueResult(handled=False, enqueued=[], failures=[])


@pytest.mark.asyncio
async def test_scheduler_heartbeat_retries_transient_deadline_without_error_traceback(caplog: pytest.LogCaptureFixture) -> None:
    stop = asyncio.Event()
    timeouts: list[float | None] = []
    health = DispatcherHealth("scheduler:test", lanes=("scheduler",), max_age_seconds=30)
    health.registered()
    health.progress("scheduler")

    class _Client(FakeSchedulerClient):
        async def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int, retry_seconds: float | None = None) -> None:
            assert worker_id == "scheduler:test"
            assert retry_seconds == 0.0
            assert health.snapshot()["registered"] is False

        async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
            assert worker_id == "scheduler:test"
            timeouts.append(timeout_seconds)
            if len(timeouts) == 1:
                raise RuntimeError("Backend scheduler gRPC failed with DEADLINE_EXCEEDED: Deadline Exceeded")
            stop.set()

    await scheduler_main._heartbeat_loop(
        client=_Client(),
        stop_event=stop,
        worker_id="scheduler:test",
        heartbeat_seconds=0.001,
        health=health,
    )

    assert timeouts == [5.0, 5.0]
    assert health.snapshot()["registered"] is True
    assert health.snapshot()["healthy"] is False
    assert [record.levelname for record in caplog.records if "Scheduler heartbeat" in record.message] == ["WARNING"]


def test_scheduler_settings_require_internal_rpc_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_GRPC_TARGET", raising=False)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "token")
    monkeypatch.setenv("SCHEDULER_CHECK_INTERVAL", "5")

    with pytest.raises(RuntimeError, match="INTERNAL_GRPC_TARGET"):
        scheduler_main.SchedulerSettings.from_env()


def test_scheduler_settings_loads_internal_rpc_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_GRPC_TARGET", "api:50051")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "token")
    monkeypatch.setenv("SCHEDULER_CHECK_INTERVAL", "5")

    settings = scheduler_main.SchedulerSettings.from_env()

    assert settings.internal_grpc_target == "api:50051"
    assert settings.internal_api_token == "token"
    assert settings.scheduler_check_interval == 5


@pytest.mark.asyncio
async def test_scheduler_loop_registers_runs_due_work_and_stops() -> None:
    client = FakeSchedulerClient()
    stop_event = asyncio.Event()

    async def stop_after_first_tick() -> None:
        while client.run_due_calls == 0:
            await asyncio.sleep(0)
        stop_event.set()

    stopper = asyncio.create_task(stop_after_first_tick())
    await scheduler_main.scheduler_loop(
        stop_event,
        "scheduler-1",
        client=client,
        health=DispatcherHealth("scheduler-1", lanes=("scheduler",), max_age_seconds=30),
        check_interval_seconds=1,
        heartbeat_seconds=60,
    )
    stopper_results = await asyncio.gather(stopper)
    assert stopper_results == [None]

    assert client.calls == [
        ("register", "scheduler-1"),
        ("due_schedule_namespaces", "default"),
        ("run_due", "scheduler-1:default"),
        ("stop", "scheduler-1"),
    ]


@pytest.mark.asyncio
async def test_scheduler_stops_starting_namespace_work_after_stop_during_rpc() -> None:
    first_started = asyncio.Event()
    allow_first_to_return = asyncio.Event()
    stop_event = asyncio.Event()

    class MultiNamespaceClient(FakeSchedulerClient):
        async def due_schedule_namespaces(self) -> list[scheduler_main.DueScheduleNamespace]:
            return [
                scheduler_main.DueScheduleNamespace(namespace="first", generation=1),
                scheduler_main.DueScheduleNamespace(namespace="second", generation=2),
            ]

        async def run_due(self, *, worker_id: str, namespace: str, generation: int, wake_ids: tuple[int, ...] = ()) -> scheduler_main.SchedulerRunDueResult:
            self.run_due_calls += 1
            self.calls.append(("run_due", f"{worker_id}:{namespace}"))
            if namespace == "first":
                first_started.set()
                await asyncio.wait_for(allow_first_to_return.wait(), timeout=5)
            return scheduler_main.SchedulerRunDueResult(handled=False, enqueued=[], failures=[])

    client = MultiNamespaceClient()
    loop_task = asyncio.create_task(
        scheduler_main.scheduler_loop(
            stop_event,
            "scheduler-stop-batch",
            client=client,
            health=DispatcherHealth("scheduler-stop-batch", lanes=("scheduler",), max_age_seconds=30),
            check_interval_seconds=1,
            heartbeat_seconds=60,
        )
    )
    try:
        await asyncio.wait_for(first_started.wait(), timeout=2)
    finally:
        stop_event.set()
        allow_first_to_return.set()
    await asyncio.wait_for(loop_task, timeout=3)

    assert client.run_due_calls == 1
    assert ("run_due", "scheduler-stop-batch:first") in client.calls
    assert ("run_due", "scheduler-stop-batch:second") not in client.calls


@pytest.mark.asyncio
async def test_scheduler_loop_retries_after_backend_restart() -> None:
    class FlakySchedulerClient(FakeSchedulerClient):
        async def run_due(self, *, worker_id: str, namespace: str, generation: int, wake_ids: tuple[int, ...] = ()) -> scheduler_main.SchedulerRunDueResult:
            assert generation == 1
            if self.run_due_calls == 0:
                self.run_due_calls += 1
                raise RuntimeError("backend unavailable")
            return await super().run_due(worker_id=worker_id, namespace=namespace, generation=generation, wake_ids=wake_ids)

    client = FlakySchedulerClient()
    stop_event = asyncio.Event()

    async def stop_after_recovery() -> None:
        while client.run_due_calls < 2:
            await asyncio.sleep(0)
        stop_event.set()

    stopper = asyncio.create_task(stop_after_recovery())
    await scheduler_main.scheduler_loop(
        stop_event,
        "scheduler-restart",
        client=client,
        health=DispatcherHealth("scheduler-restart", lanes=("scheduler",), max_age_seconds=30),
        check_interval_seconds=1,
        heartbeat_seconds=60,
    )
    await stopper

    assert client.run_due_calls == 2


@pytest.mark.asyncio
async def test_stalled_scheduler_dispatch_expires_health_while_heartbeat_continues() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    heartbeat_seen = asyncio.Event()
    now = 100.0
    health = DispatcherHealth("scheduler:hung", lanes=("scheduler",), max_age_seconds=45, clock=lambda: now)

    class StalledSchedulerClient(FakeSchedulerClient):
        async def run_due(self, *, worker_id: str, namespace: str, generation: int, wake_ids: tuple[int, ...] = ()) -> scheduler_main.SchedulerRunDueResult:
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=5)
            return await super().run_due(worker_id=worker_id, namespace=namespace, generation=generation, wake_ids=wake_ids)

        async def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
            heartbeat_seen.set()

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        scheduler_main.scheduler_loop(
            stop_event,
            "scheduler:hung",
            client=StalledSchedulerClient(),
            health=health,
            check_interval_seconds=1,
            heartbeat_seconds=0.001,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert health.snapshot()["healthy"] is True
        now += 46
        await asyncio.wait_for(heartbeat_seen.wait(), timeout=1)
        assert health.snapshot()["healthy"] is False
    finally:
        stop_event.set()
        release.set()
        await task
