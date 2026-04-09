from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from modules.engine_runs import schemas

logger = logging.getLogger(__name__)


def _is_expected_send_shutdown(websocket: WebSocket, exc: Exception) -> bool:
    if isinstance(exc, WebSocketDisconnect):
        return True
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return True
    if websocket.application_state is WebSocketState.DISCONNECTED:
        return True
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc)
    return 'Unexpected ASGI message' in message and 'websocket.send' in message


@dataclass(slots=True)
class EngineRunListWatcher:
    websocket: WebSocket
    loop: asyncio.AbstractEventLoop
    params: schemas.EngineRunListParams
    run_ids: tuple[str, ...] = ()


class EngineRunWatcherRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._watchers: dict[str, dict[WebSocket, EngineRunListWatcher]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def add(
        self,
        namespace: str,
        websocket: WebSocket,
        *,
        loop: asyncio.AbstractEventLoop,
        params: schemas.EngineRunListParams,
    ) -> None:
        with self._lock:
            self._watchers.setdefault(namespace, {})[websocket] = EngineRunListWatcher(
                websocket=websocket,
                loop=loop,
                params=params,
            )

    def discard(self, namespace: str, websocket: WebSocket) -> None:
        with self._lock:
            watchers = self._watchers.get(namespace)
            if watchers is None:
                return
            watchers.pop(websocket, None)
            if watchers:
                return
            self._watchers.pop(namespace, None)

    def watchers(self, namespace: str) -> list[EngineRunListWatcher]:
        with self._lock:
            return list(self._watchers.get(namespace, {}).values())

    def set_run_ids(self, namespace: str, websocket: WebSocket, run_ids: tuple[str, ...]) -> None:
        with self._lock:
            watchers = self._watchers.get(namespace)
            if watchers is None:
                return
            watcher = watchers.get(websocket)
            if watcher is None:
                return
            watcher.run_ids = run_ids

    def clear(self) -> None:
        with self._lock:
            self._watchers.clear()

    def broadcast(self, namespace: str, payloads: list[tuple[EngineRunListWatcher, dict[str, Any]]]) -> None:
        for watcher, payload in payloads:
            try:
                watcher.loop.call_soon_threadsafe(self._schedule_send, namespace, watcher.websocket, payload)
            except RuntimeError:
                self.discard(namespace, watcher.websocket)

    def _schedule_send(self, namespace: str, websocket: WebSocket, payload: dict[str, Any]) -> None:
        task = asyncio.create_task(self._send(namespace, websocket, payload))
        with self._lock:
            self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        with self._lock:
            self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            'Engine run watcher task failed unexpectedly',
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    async def _send(self, namespace: str, websocket: WebSocket, payload: dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception as exc:
            if _is_expected_send_shutdown(websocket, exc):
                self.discard(namespace, websocket)
                return
            logger.warning('Engine run watcher send failed: %s', exc, exc_info=True)
            self.discard(namespace, websocket)


registry = EngineRunWatcherRegistry()
