import asyncio
from collections import defaultdict

from fastapi import WebSocket

LockKey = tuple[str, str, str]


class LockWatcherRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._watchers: defaultdict[LockKey, set[WebSocket]] = defaultdict(set)

    async def add(self, websocket: WebSocket, namespace: str, resource_type: str, resource_id: str) -> None:
        key = (namespace, resource_type, resource_id)
        async with self._lock:
            self._watchers[key].add(websocket)

    async def discard(self, websocket: WebSocket, namespace: str, resource_type: str, resource_id: str) -> None:
        key = (namespace, resource_type, resource_id)
        async with self._lock:
            sockets = self._watchers.get(key)
            if sockets is None:
                return
            sockets.discard(websocket)
            if sockets:
                return
            self._watchers.pop(key, None)

    async def sockets(self, namespace: str, resource_type: str, resource_id: str) -> list[WebSocket]:
        key = (namespace, resource_type, resource_id)
        async with self._lock:
            return list(self._watchers.get(key, set()))

    async def clear(self) -> None:
        async with self._lock:
            self._watchers.clear()


registry = LockWatcherRegistry()
