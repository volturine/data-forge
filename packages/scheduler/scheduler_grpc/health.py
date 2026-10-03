from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

_ROLE = "scheduler"


def _socket_path(pid: int) -> Path:
    return Path("/tmp") / f"dataforge-{_ROLE}-health-{pid}.sock"


class DispatcherHealth:
    """Process-owned registration and dispatch progress, independent of heartbeats."""

    def __init__(self, worker_id: str, *, lanes: tuple[str, ...], max_age_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.worker_id = worker_id
        self.pid = os.getpid()
        self._registered = False
        self._running = True
        self._progress: dict[str, float | None] = dict.fromkeys(lanes)
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    def registered(self) -> None:
        self.registration_changed(True)

    def registration_changed(self, registered: bool) -> None:
        self._registered = registered and self._running
        if not registered:
            self._progress = dict.fromkeys(self._progress)

    def progress(self, lane: str) -> None:
        self._progress[lane] = self._clock()

    def stopped(self) -> None:
        self._running = False
        self.registration_changed(False)

    def failed(self, lane: str) -> None:
        self._progress[lane] = None

    def snapshot(self) -> dict[str, object]:
        now = self._clock()
        ages = {lane: now - stamp if stamp is not None else None for lane, stamp in self._progress.items()}
        return {
            "pid": self.pid,
            "worker_id": self.worker_id,
            "registered": self._registered,
            "progress_age_seconds": ages,
            "healthy": self._registered and bool(ages) and all(age is not None and 0 <= age <= self._max_age_seconds for age in ages.values()),
        }

    @contextlib.asynccontextmanager
    async def serve(self) -> AsyncIterator[None]:
        path = _socket_path(self.pid)
        path.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(self._respond, path=str(path))
        try:
            yield
        finally:
            self.stopped()
            server.close()
            await server.wait_closed()
            path.unlink(missing_ok=True)

    async def _respond(self, _reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            writer.write(json.dumps(self.snapshot()).encode())
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()


def probe(pid: int = 1) -> bool:
    """Docker probes PID1's own endpoint; another instance cannot satisfy it."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            client.connect(str(_socket_path(pid)))
            chunks: list[bytes] = []
            size = 0
            while chunk := client.recv(4096):
                size += len(chunk)
                if size > 4096:
                    return False
                chunks.append(chunk)
            response = json.loads(b"".join(chunks))
        return isinstance(response, dict) and response.get("pid") == pid and response.get("registered") is True and response.get("healthy") is True
    except OSError, ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if probe() else 1)
