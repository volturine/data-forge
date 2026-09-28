from __future__ import annotations

import asyncio
import os
import threading
from typing import cast

import pytest

import main as scheduler_main


class FakeSchedulerClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.run_due_calls = 0

    def register(self, *, worker_id: str, hostname: str, pid: int, capacity: int) -> None:
        assert hostname
        assert pid == os.getpid()
        assert capacity == 1
        self.calls.append(("register", worker_id))

    def heartbeat(self, *, worker_id: str) -> None:
        self.calls.append(("heartbeat", worker_id))

    def stop(self, *, worker_id: str) -> None:
        self.calls.append(("stop", worker_id))

    def due_schedule_namespaces(self) -> list[scheduler_main.DueScheduleNamespace]:
        self.calls.append(("due_schedule_namespaces", "default"))
        return [scheduler_main.DueScheduleNamespace(namespace="default", generation=1)]

    def run_due(self, *, worker_id: str, namespace: str, generation: int) -> scheduler_main.SchedulerRunDueResult:
        assert generation == 1
        self.run_due_calls += 1
        self.calls.append(("run_due", f"{worker_id}:{namespace}"))
        return scheduler_main.SchedulerRunDueResult(handled=False, enqueued=[], failures=[])


def test_scheduler_heartbeat_retries_transient_deadline_without_error_traceback(caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    timeouts: list[float | None] = []

    class _Client:
        def heartbeat(self, *, worker_id: str, timeout_seconds: float | None = None) -> None:
            assert worker_id == "scheduler:test"
            timeouts.append(timeout_seconds)
            if len(timeouts) == 1:
                raise RuntimeError("Backend scheduler gRPC failed with DEADLINE_EXCEEDED: Deadline Exceeded")
            stop.set()

    scheduler_main._heartbeat_loop_sync(
        client=cast(scheduler_main.SchedulerApiClient, _Client()),
        stop_signal=stop,
        worker_id="scheduler:test",
        heartbeat_seconds=0.001,
    )

    assert timeouts == [5.0, 5.0]
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
        client=cast(scheduler_main.SchedulerApiClient, client),
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
async def test_scheduler_loop_retries_after_backend_restart() -> None:
    class FlakySchedulerClient(FakeSchedulerClient):
        def run_due(self, *, worker_id: str, namespace: str, generation: int) -> scheduler_main.SchedulerRunDueResult:
            assert generation == 1
            if self.run_due_calls == 0:
                self.run_due_calls += 1
                raise RuntimeError("backend unavailable")
            return super().run_due(worker_id=worker_id, namespace=namespace, generation=generation)

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
        client=cast(scheduler_main.SchedulerApiClient, client),
        check_interval_seconds=1,
        heartbeat_seconds=60,
    )
    await stopper

    assert client.run_due_calls == 2
