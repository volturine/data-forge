from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

_ROLE = "worker"


def _socket_path(pid: int) -> Path:
    return Path("/tmp") / f"dataforge-{_ROLE}-health-{pid}.sock"


class DispatcherHealth:
    """Process-owned registration and dispatch progress, independent of heartbeats."""

    def __init__(
        self,
        worker_id: str,
        *,
        lanes: tuple[str, ...],
        max_age_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.worker_id = worker_id
        self.pid = os.getpid()
        self._registered = False
        self._running = True
        # One object follows the process through its roles. "starting" is a
        # cold start: unhealthy until the manager is registered, so a machine's
        # API only starts once compute is really there. "standby" holds no
        # registration and dispatches nothing; it is healthy while the lease
        # wait loop answers here. "taking_over" is a standby that just won the
        # lease, or a manager waiting for a new coordinator generation: it
        # sweeps every host and rebuilds the warm reserve before it can
        # register, so it stays healthy for a bounded grace period.
        self._state = "starting"
        self._taking_over_until = 0.0
        self._progress: dict[str, float | None] = dict.fromkeys(lanes)
        self._max_age_seconds = max_age_seconds
        self._clock = clock

    @property
    def state(self) -> str:
        return self._state

    def standby(self) -> None:
        self.registration_changed(False)
        if self._running:
            self._state = "standby"

    def taking_over(self, grace_seconds: float) -> None:
        self.registration_changed(False)
        if not self._running:
            return
        # A takeover that keeps failing before it registers must not refresh
        # its own grace period; only a registration starts the clock again.
        if self._state != "taking_over":
            self._taking_over_until = self._clock() + max(grace_seconds, 0.0)
        self._state = "taking_over"

    def registered(self) -> None:
        self.registration_changed(True)

    def registration_changed(self, registered: bool) -> None:
        self._registered = registered and self._running
        if self._registered:
            self._state = "active"
        else:
            self._progress = dict.fromkeys(self._progress)

    def progress(self, lane: str) -> None:
        self._progress[lane] = self._clock()

    def stopped(self) -> None:
        self._running = False
        self._state = "stopped"
        self.registration_changed(False)

    def failed(self, lane: str) -> None:
        self._progress[lane] = None

    def snapshot(self) -> dict[str, object]:
        now = self._clock()
        ages = {lane: now - stamp if stamp is not None else None for lane, stamp in self._progress.items()}
        if not self._running:
            healthy = False
        elif self._state == "standby":
            healthy = True
        elif self._state == "taking_over":
            healthy = now < self._taking_over_until
        else:
            healthy = self._registered and bool(ages) and all(age is not None and 0 <= age <= self._max_age_seconds for age in ages.values())
        return {
            "pid": self.pid,
            "worker_id": self.worker_id,
            "state": self._state,
            "registered": self._registered,
            "progress_age_seconds": ages,
            "healthy": healthy,
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
        if not isinstance(response, dict) or response.get("pid") != pid or response.get("healthy") is not True:
            return False
        return response.get("registered") is True or response.get("state") in {"standby", "taking_over"}
    except OSError, ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if probe() else 1)
