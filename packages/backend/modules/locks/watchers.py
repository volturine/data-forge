import asyncio
from collections import defaultdict

from fastapi import WebSocket
from pydantic import BaseModel

from backend_core.websocket import safe_send_serialized_json, serialize_json

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


async def notify_watchers(
    namespace: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object] | BaseModel,
) -> None:
    sockets = await registry.sockets(namespace, resource_type, resource_id)
    if not sockets:
        return
    try:
        serialized = await serialize_json(payload)
    except Exception:
        for websocket in sockets:
            await registry.discard(websocket, namespace, resource_type, resource_id)
        return

    async def _notify(websocket: WebSocket) -> tuple[WebSocket, bool]:
        try:
            # A disconnected or backpressured browser must not make the lock
            # mutation request wait behind every other watcher. The next
            # connection reads the durable lock state on subscribe.
            sent = await asyncio.wait_for(safe_send_serialized_json(websocket, serialized), timeout=1.0)
        except Exception:
            return websocket, False
        return websocket, sent

    results = await asyncio.gather(
        *(_notify(websocket) for websocket in sockets),
    )
    stale = [websocket for websocket, sent in results if not sent]
    for websocket in stale:
        await registry.discard(websocket, namespace, resource_type, resource_id)
