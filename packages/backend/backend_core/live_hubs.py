from __future__ import annotations

import asyncio
import threading

DEFAULT_MAX_WAITERS = 1024

_Waiter = tuple[asyncio.AbstractEventLoop, asyncio.Future[int]]


def _cancel_waiter(entry: _Waiter) -> None:
    loop, future = entry
    if future.done():
        return
    try:
        loop.call_soon_threadsafe(future.cancel)
    except RuntimeError:
        future.cancel()


class VersionHub:
    def __init__(self, *, max_waiters: int = DEFAULT_MAX_WAITERS) -> None:
        self._version = 0
        self._waiters: list[_Waiter] = []
        self._lock = threading.Lock()
        self._max_waiters = max_waiters

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
        evicted: list[_Waiter] = []
        with self._lock:
            version = self._version
            if last_seen is not None and version != last_seen:
                return version
            self._waiters = [(item_loop, item) for item_loop, item in self._waiters if not item.done()]
            self._waiters.append((loop, future))
            evicted = self._evict_overflow_locked()
        for entry in evicted:
            if entry[1] is not future:
                _cancel_waiter(entry)
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

    def _evict_overflow_locked(self) -> list[_Waiter]:
        if len(self._waiters) <= self._max_waiters:
            return []
        evicted = self._waiters[: -self._max_waiters]
        self._waiters = self._waiters[-self._max_waiters :]
        return evicted

    async def _discard_waiter(self, future: asyncio.Future[int]) -> None:
        with self._lock:
            self._waiters = [(loop, item) for loop, item in self._waiters if item is not future and not item.done()]

    @staticmethod
    def _resolve_waiter(future: asyncio.Future[int], version: int) -> None:
        if future.done():
            return
        future.set_result(version)


class KeyedVersionHub:
    def __init__(self, *, max_waiters: int = DEFAULT_MAX_WAITERS) -> None:
        self._versions: dict[str, int] = {}
        self._waiters: dict[str, list[_Waiter]] = {}
        self._lock = threading.Lock()
        self._max_waiters = max_waiters

    def publish(self, key: str) -> None:
        with self._lock:
            version = self._versions.get(key, 0) + 1
            self._versions[key] = version
            waiters = self._waiters.pop(key, [])
        for loop, future in waiters:
            if future.done():
                continue
            loop.call_soon_threadsafe(self._resolve_waiter, future, version)

    def waiter_count(self) -> int:
        with self._lock:
            return sum(len(entries) for entries in self._waiters.values())

    async def wait(self, key: str, last_seen: int | None = None) -> int:
        with self._lock:
            version = self._versions.get(key, 0)
            if last_seen is not None and version != last_seen:
                return version
        loop = asyncio.get_running_loop()
        future: asyncio.Future[int] = loop.create_future()
        evicted: list[_Waiter] = []
        with self._lock:
            version = self._versions.get(key, 0)
            if last_seen is not None and version != last_seen:
                return version
            current = [entry for entry in self._waiters.get(key, []) if not entry[1].done()]
            if current:
                self._waiters[key] = current
            else:
                self._waiters.pop(key, None)
            self._waiters.setdefault(key, []).append((loop, future))
            evicted = self._evict_overflow_locked()
        for entry in evicted:
            if entry[1] is not future:
                _cancel_waiter(entry)
        try:
            return await future
        finally:
            await self._discard_waiter(key, future)

    async def clear(self) -> None:
        with self._lock:
            waiters = self._waiters
            self._waiters = {}
            self._versions = {}
        for items in waiters.values():
            for loop, future in items:
                if future.done():
                    continue
                loop.call_soon_threadsafe(future.cancel)

    def _evict_overflow_locked(self) -> list[_Waiter]:
        total = sum(len(entries) for entries in self._waiters.values())
        if total <= self._max_waiters:
            return []
        evicted: list[_Waiter] = []
        for key in list(self._waiters):
            entries = self._waiters.get(key)
            while entries and total > self._max_waiters:
                evicted.append(entries.pop(0))
                total -= 1
            if entries:
                self._waiters[key] = entries
            else:
                self._waiters.pop(key, None)
            if total <= self._max_waiters:
                break
        return evicted

    async def _discard_waiter(self, key: str, future: asyncio.Future[int]) -> None:
        with self._lock:
            current = self._waiters.get(key)
            if current is None:
                return
            next_waiters = [(loop, item) for loop, item in current if item is not future and not item.done()]
            if next_waiters:
                self._waiters[key] = next_waiters
                return
            self._waiters.pop(key, None)

    @staticmethod
    def _resolve_waiter(future: asyncio.Future[int], version: int) -> None:
        if future.done():
            return
        future.set_result(version)
