from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from runtime import runtime_ipc


@pytest.mark.asyncio
async def test_runtime_listener_delivers_notifications_and_stops() -> None:
    stop_event = asyncio.Event()
    notification_ready = asyncio.Event()
    received: list[dict[str, object]] = []

    class FakeConnection:
        async def notifies(self, *, timeout: float, stop_after: int):
            del timeout, stop_after
            await notification_ready.wait()
            yield SimpleNamespace(payload=json.dumps({"kind": "job"}))

    async def handle(payload: dict[str, object]) -> None:
        received.append(payload)
        stop_event.set()

    listener = runtime_ipc.RuntimeNotificationListener(FakeConnection())
    task = asyncio.create_task(runtime_ipc.serve_runtime_notifications(listener, stop_event, handle))
    await asyncio.sleep(0)
    assert not task.done()
    notification_ready.set()
    await asyncio.wait_for(task, timeout=1.0)
    await runtime_ipc.stop_runtime_listener(listener)

    assert received == [{"kind": "job"}]


@pytest.mark.asyncio
async def test_runtime_listener_reconnects_after_database_disconnect(monkeypatch) -> None:
    stop_event = asyncio.Event()
    received: list[dict[str, object]] = []

    class FakeConnection:
        def __init__(self, *, disconnected: bool = False) -> None:
            self.disconnected = disconnected
            self.closed = False

        async def notifies(self, *, timeout: float, stop_after: int):
            del timeout, stop_after
            if self.disconnected:
                raise runtime_ipc.psycopg.OperationalError("connection lost")
            yield SimpleNamespace(payload=json.dumps({"kind": "reconnected"}))

        async def close(self) -> None:
            self.closed = True

    disconnected = FakeConnection(disconnected=True)
    reconnected = FakeConnection()
    listener = runtime_ipc.RuntimeNotificationListener(disconnected)
    open_calls = 0

    async def open_listener() -> FakeConnection:
        nonlocal open_calls
        open_calls += 1
        return reconnected

    monkeypatch.setattr(runtime_ipc, "_open_runtime_listener", open_listener)

    async def skip_backoff(_stop_event: asyncio.Event, _delay_seconds: float) -> bool:
        return False

    monkeypatch.setattr(runtime_ipc, "_wait_for_reconnect", skip_backoff)

    async def handle(payload: dict[str, object]) -> None:
        received.append(payload)
        stop_event.set()

    task = asyncio.create_task(runtime_ipc.serve_runtime_notifications(listener, stop_event, handle))
    await asyncio.wait_for(task, timeout=1.0)
    await runtime_ipc.stop_runtime_listener(listener)

    assert open_calls == 1
    assert disconnected.closed
    assert reconnected.closed
    assert received == [{"kind": "reconnected"}]


@pytest.mark.asyncio
async def test_notification_bursts_yield_to_other_runtime_tasks() -> None:
    stop_event = asyncio.Event()
    heartbeat_ran = False

    class FakeConnection:
        async def notifies(self, *, timeout: float, stop_after: int):
            del timeout, stop_after
            for sequence in range(130):
                yield SimpleNamespace(payload=json.dumps({"sequence": sequence}))

        async def close(self) -> None:
            return None

    async def heartbeat() -> None:
        nonlocal heartbeat_ran
        await asyncio.sleep(0)
        heartbeat_ran = True

    async def handle(payload: dict[str, object]) -> None:
        if payload["sequence"] == 129:
            assert heartbeat_ran
            stop_event.set()

    listener = runtime_ipc.RuntimeNotificationListener(FakeConnection())
    listener_task = asyncio.create_task(runtime_ipc.serve_runtime_notifications(listener, stop_event, handle))
    heartbeat_task = asyncio.create_task(heartbeat())
    await asyncio.wait_for(asyncio.gather(listener_task, heartbeat_task), timeout=1.0)
    await runtime_ipc.stop_runtime_listener(listener)
