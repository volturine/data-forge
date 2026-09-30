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
        self._versions: dict[LockKey, int] = {}
        self._delivery_locks: dict[LockKey, asyncio.Lock] = {}
        self._next_version = 0

    async def add(self, websocket: WebSocket, namespace: str, resource_type: str, resource_id: str) -> None:
        key = (namespace, resource_type, resource_id)
        async with self._lock:
            if key not in self._watchers:
                self._next_version += 1
                self._versions[key] = self._next_version
                self._delivery_locks[key] = asyncio.Lock()
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
            self._versions.pop(key, None)
            self._delivery_locks.pop(key, None)

    async def current_version(self, namespace: str, resource_type: str, resource_id: str) -> int:
        async with self._lock:
            return self._versions.get((namespace, resource_type, resource_id), 0)

    async def active_keys(self) -> list[tuple[LockKey, int]]:
        async with self._lock:
            return list(self._versions.items())

    async def sockets(self, namespace: str, resource_type: str, resource_id: str) -> list[WebSocket]:
        key = (namespace, resource_type, resource_id)
        async with self._lock:
            return list(self._watchers.get(key, set()))

    async def clear(self) -> None:
        async with self._lock:
            self._watchers.clear()
            self._versions.clear()
            self._delivery_locks.clear()


registry = LockWatcherRegistry()


async def notify_watchers(
    namespace: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object] | BaseModel,
) -> bool:
    return await _deliver_status(namespace, resource_type, resource_id, payload, expected_version=None)


async def refresh_watchers(
    namespace: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object] | BaseModel,
    *,
    expected_version: int,
) -> bool:
    """Send a durable snapshot only if no newer publication won its DB read."""
    return await _deliver_status(namespace, resource_type, resource_id, payload, expected_version=expected_version)


async def _deliver_status(
    namespace: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object] | BaseModel,
    *,
    expected_version: int | None,
) -> bool:
    key = (namespace, resource_type, resource_id)
    async with registry._lock:
        delivery_lock = registry._delivery_locks.get(key)
    if delivery_lock is None:
        return False
    # Serialize sends for one resource, never the DB read or another resource.
    # A publication racing an accepted snapshot is therefore sent after it.
    async with delivery_lock:
        async with registry._lock:
            if registry._delivery_locks.get(key) is not delivery_lock:
                return False
            if expected_version is not None and registry._versions.get(key) != expected_version:
                return False
            registry._next_version += 1
            registry._versions[key] = registry._next_version
            sockets = list(registry._watchers[key])
        return await _send_status(namespace, resource_type, resource_id, payload, sockets)


async def _send_status(namespace: str, resource_type: str, resource_id: str, payload: dict[str, object] | BaseModel, sockets: list[WebSocket]) -> bool:
    if not sockets:
        return False
    try:
        serialized = await serialize_json(payload)
    except Exception:
        for websocket in sockets:
            await registry.discard(websocket, namespace, resource_type, resource_id)
        return False

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
    return True
