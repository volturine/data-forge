from __future__ import annotations

import asyncio
import os

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

    def run_due(self, *, worker_id: str) -> dict[str, object]:
        self.run_due_calls += 1
        self.calls.append(("run_due", worker_id))
        return {"handled": False, "enqueued": [], "failures": []}


def test_scheduler_settings_require_internal_rpc_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_API_BASE_URL", raising=False)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "token")
    monkeypatch.setenv("SCHEDULER_CHECK_INTERVAL", "5")

    with pytest.raises(RuntimeError, match="INTERNAL_API_BASE_URL"):
        scheduler_main.SchedulerSettings.from_env()


def test_scheduler_settings_loads_internal_rpc_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_BASE_URL", "http://api:8000/api/v1/internal/")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "token")
    monkeypatch.setenv("SCHEDULER_CHECK_INTERVAL", "5")

    settings = scheduler_main.SchedulerSettings.from_env()

    assert settings.internal_api_base_url == "http://api:8000/api/v1/internal"
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
        client=client,  # type: ignore[arg-type]
        check_interval_seconds=1,
        heartbeat_seconds=60,
    )
    await stopper

    assert client.calls == [
        ("register", "scheduler-1"),
        ("run_due", "scheduler-1"),
        ("stop", "scheduler-1"),
    ]
