from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict, deque

DEFAULT_MAX_WAITERS = 1024
_MAX_KEYED_VERSIONS = 4096

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
        self._history: deque[tuple[int, str | None]] = deque(maxlen=2048)
        self._waiters: list[_Waiter] = []
        self._lock = threading.Lock()
        self._max_waiters = max_waiters

    def publish(self, payload: str | None = None) -> None:
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

    def payloads_since(self, last_seen: int) -> list[str | None]:
        """Return distinct payloads published after ``last_seen``.

        The history is only an admission hint. Durable outbox recovery uses
        the indexed pending-work table when a listener outage overruns this
        bounded buffer.
        """
        with self._lock:
            if last_seen >= self._version:
                return []
            if not self._history or self._history[0][0] > last_seen + 1:
                return [self._history[-1][1]] if self._history else []
            payloads: list[str | None] = []
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
            self._history.clear()
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
    def __init__(self) -> None:
        self._versions: OrderedDict[str, int] = OrderedDict()
        self._waiters: dict[str, list[_Waiter]] = {}
        self._lock = threading.Lock()

    def publish(self, key: str) -> None:
        with self._lock:
            version = self._versions.get(key, 0) + 1
            self._versions[key] = version
            self._versions.move_to_end(key)
            # This hub is only a wakeup optimization; durable request state
            # and the bounded recovery poller remain authoritative.
            while len(self._versions) > _MAX_KEYED_VERSIONS:
                self._versions.popitem(last=False)
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
        try:
            return await future
        finally:
            await self._discard_waiter(key, future)

    async def clear(self) -> None:
        with self._lock:
            waiters = self._waiters
            self._waiters = {}
            self._versions = OrderedDict()
        for items in waiters.values():
            for loop, future in items:
                if future.done():
                    continue
                loop.call_soon_threadsafe(future.cancel)

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
