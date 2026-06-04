from __future__ import annotations

import asyncio
import threading


class BuildJobHub:
    def __init__(self) -> None:
        self._version = 0
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future[int]]] = []
        self._lock = threading.Lock()

    def publish(self) -> None:
        with self._lock:
            self._version += 1
            version = self._version
            waiters = self._waiters
            self._waiters = []
        for loop, future in waiters:
            if future.done():
                continue
            loop.call_soon_threadsafe(self._resolve_waiter, future, version)

    def version(self) -> int:
        with self._lock:
            return self._version

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


hub = BuildJobHub()
