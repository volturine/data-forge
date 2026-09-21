from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from runtime import runtime_ipc


@pytest.mark.asyncio
async def test_runtime_listener_delivers_notifications_and_stops() -> None:
    read_fd, write_fd = os.pipe()
    stop_event = asyncio.Event()
    received: list[dict[str, object]] = []

    class FakeConnection:
        closed = False

        def fileno(self) -> int:
            return read_fd

        def notifies(self, *, timeout: float, stop_after: int):
            del timeout, stop_after
            os.read(read_fd, 1)
            return [SimpleNamespace(payload=json.dumps({"kind": "job"}))]

    async def handle(payload: dict[str, object]) -> None:
        received.append(payload)
        stop_event.set()

    task = asyncio.create_task(runtime_ipc.serve_runtime_notifications(FakeConnection(), stop_event, handle))
    try:
        os.write(write_fd, b"1")
        await asyncio.wait_for(task, timeout=1.0)
    finally:
        if not task.done():
            stop_event.set()
            await task
        os.close(read_fd)
        os.close(write_fd)

    assert received == [{"kind": "job"}]
