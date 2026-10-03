from __future__ import annotations

import asyncio
import threading
from collections import deque


class VersionHub[T]:
    def __init__(self) -> None:
        self._version = 0
        self._history: deque[tuple[int, T | None]] = deque(maxlen=2048)
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[int]]] = []
        self._lock = threading.Lock()

    def publish(self, payload: T | None = None) -> None:
        with self._lock:
            self._version += 1
            version = self._version
            self._history.append((version, payload))
            waiters = self._waiters
            self._waiters = []
        for loop, future in waiters:
            if future.done():
                continue
            loop.call_soon_threadsafe(self._resolve_waiter, future, version)

    def version(self) -> int:
        with self._lock:
            return self._version

    def payloads_since(self, last_seen: int) -> list[T | None]:
        """Return namespace payloads published after ``last_seen``.

        A bounded history lets every claim lane observe every namespace from a
        burst without making the notification itself a global queue. If the
        history was overrun, returning the newest payload leaves the durable
        recovery poll to find anything older without reintroducing a tenant
        scan on the claim path.
        """
        with self._lock:
            if last_seen >= self._version:
                return []
            if not self._history or self._history[0][0] > last_seen + 1:
                return [self._history[-1][1]] if self._history else []
            payloads: list[T | None] = []
            for version, payload in self._history:
                if version <= last_seen or payload in payloads:
                    continue
                payloads.append(payload)
            return payloads

    async def wait(self, last_seen: int | None = None) -> int:
        with self._lock:
            version = self._version
            if last_seen is not None and version != last_seen:
                return version
        loop = asyncio.get_running_loop()
        future: asyncio.Future[int] = loop.create_future()
        with self._lock:
            version = self._version
            if last_seen is not None and version != last_seen:
                return version
            self._waiters.append((loop, future))
        try:
            return await future
        finally:
            await self._discard_waiter(future)

    async def clear(self) -> None:
        with self._lock:
            waiters = self._waiters
            self._waiters = []
            self._version = 0
            self._history.clear()
        for loop, future in waiters:
            if future.done():
                continue
            loop.call_soon_threadsafe(future.cancel)

    async def _discard_waiter(self, future: asyncio.Future[int]) -> None:
        with self._lock:
            self._waiters = [(loop, item) for loop, item in self._waiters if item is not future and not item.done()]

    @staticmethod
    def _resolve_waiter(future: asyncio.Future[int], version: int) -> None:
        if future.done():
            return
        future.set_result(version)
