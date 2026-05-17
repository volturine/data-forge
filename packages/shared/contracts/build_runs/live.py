from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuildNotification:
    namespace: str
    build_id: str
    latest_sequence: int


class BuildNotificationHub:
    def __init__(self) -> None:
        self._build_waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Future[BuildNotification]]]] = {}
        self._namespace_waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Future[BuildNotification]]]] = {}
        self._latest_by_build: dict[str, BuildNotification] = {}
        self._latest_by_namespace: dict[str, BuildNotification] = {}
        self._namespace_version: dict[str, int] = {}
        self._lock = threading.Lock()

    async def publish(self, notification: BuildNotification) -> None:
        with self._lock:
            self._latest_by_build[notification.build_id] = notification
            self._latest_by_namespace[notification.namespace] = notification
            self._namespace_version[notification.namespace] = self._namespace_version.get(notification.namespace, 0) + 1
            build_waiters = self._build_waiters.pop(notification.build_id, [])
            namespace_waiters = self._namespace_waiters.pop(notification.namespace, [])
        for loop, future in [*build_waiters, *namespace_waiters]:
            if future.done():
                continue
            loop.call_soon_threadsafe(self._resolve_waiter, future, notification)

    async def wait_for_build(self, build_id: str, last_sequence: int = 0) -> BuildNotification:
        with self._lock:
            current = self._latest_by_build.get(build_id)
            if current is not None and current.latest_sequence > last_sequence:
                return current
        loop = asyncio.get_running_loop()
        future: asyncio.Future[BuildNotification] = loop.create_future()
        with self._lock:
            current = self._latest_by_build.get(build_id)
            if current is not None and current.latest_sequence > last_sequence:
                return current
            self._build_waiters.setdefault(build_id, []).append((loop, future))
        try:
            return await future
        finally:
            await self._discard_waiter(self._build_waiters, build_id, future)

    async def wait_for_namespace(self, namespace: str, last_version: int = 0) -> BuildNotification:
        with self._lock:
            current = self._latest_by_namespace.get(namespace)
            current_version = self._namespace_version.get(namespace, 0)
            if current is not None and current_version > last_version:
                return current
        loop = asyncio.get_running_loop()
        future: asyncio.Future[BuildNotification] = loop.create_future()
        with self._lock:
            current = self._latest_by_namespace.get(namespace)
            current_version = self._namespace_version.get(namespace, 0)
            if current is not None and current_version > last_version:
                return current
            self._namespace_waiters.setdefault(namespace, []).append((loop, future))
        try:
            return await future
        finally:
            await self._discard_waiter(self._namespace_waiters, namespace, future)

    def latest_namespace_sequence(self, namespace: str) -> int:
        with self._lock:
            return self._namespace_version.get(namespace, 0)

    async def clear(self) -> None:
        with self._lock:
            build_waiters = self._build_waiters
            namespace_waiters = self._namespace_waiters
            self._build_waiters = {}
            self._namespace_waiters = {}
            self._latest_by_build = {}
            self._latest_by_namespace = {}
            self._namespace_version = {}
        for waiters in [*build_waiters.values(), *namespace_waiters.values()]:
            for loop, future in waiters:
                if future.done():
                    continue
                loop.call_soon_threadsafe(future.cancel)

    async def _discard_waiter(
        self, waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Future[BuildNotification]]]], key: str, future: asyncio.Future[BuildNotification]
    ) -> None:
        with self._lock:
            current = waiters.get(key)
            if current is None:
                return
            next_waiters = [(loop, item) for loop, item in current if item is not future and not item.done()]
            if next_waiters:
                waiters[key] = next_waiters
                return
            waiters.pop(key, None)

    @staticmethod
    def _resolve_waiter(future: asyncio.Future[BuildNotification], notification: BuildNotification) -> None:
        if future.done():
            return
        future.set_result(notification)


hub = BuildNotificationHub()
