from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import WebSocket

from core.namespace import get_namespace
from modules.compute import schemas
from modules.compute.core.base import EngineStatusInfo


class EngineRegistry:
    def __init__(self) -> None:
        self._watchers: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def add_watcher(self, namespace: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._watchers.setdefault(namespace, set()).add(websocket)

    async def remove_watcher(self, namespace: str, websocket: WebSocket) -> None:
        async with self._lock:
            watchers = self._watchers.get(namespace)
            if not watchers:
                return
            watchers.discard(websocket)
            if watchers:
                return
            self._watchers.pop(namespace, None)

    async def clear(self) -> None:
        async with self._lock:
            self._watchers.clear()

    async def publish_snapshot(self, namespace: str, statuses: list[EngineStatusInfo]) -> None:
        payload = schemas.EngineListSnapshotMessage(
            engines=[schemas.EngineStatusSchema.model_validate(status) for status in statuses],
            total=len(statuses),
        ).model_dump(mode='json')
        async with self._lock:
            watchers = list(self._watchers.get(namespace, set()))
        stale: list[WebSocket] = []
        for websocket in watchers:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        if not stale:
            return
        async with self._lock:
            current = self._watchers.get(namespace)
            if current is None:
                return
            for websocket in stale:
                current.discard(websocket)
            if current:
                return
            self._watchers.pop(namespace, None)


registry = EngineRegistry()


def create_snapshot_notifier(loop: asyncio.AbstractEventLoop) -> Callable[[list[EngineStatusInfo]], None]:
    def notify(statuses: list[EngineStatusInfo]) -> None:
        if loop.is_closed():
            return
        namespace = get_namespace()
        loop.call_soon_threadsafe(loop.create_task, registry.publish_snapshot(namespace, statuses))

    return notify
