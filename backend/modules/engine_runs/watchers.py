import asyncio
from dataclasses import dataclass

from fastapi import WebSocket
from fastapi.concurrency import run_in_threadpool

from core.database import run_db
from core.namespace import reset_namespace, set_namespace_context
from modules.engine_runs import schemas


@dataclass(frozen=True, slots=True)
class EngineRunWatch:
    namespace: str
    analysis_id: str | None = None
    datasource_id: str | None = None
    kind: schemas.EngineRunKind | None = None
    status: schemas.EngineRunStatus | None = None
    limit: int = 100
    offset: int = 0

    @classmethod
    def from_params(cls, namespace: str, params: schemas.EngineRunListParams) -> 'EngineRunWatch':
        return cls(
            namespace=namespace,
            analysis_id=params.analysis_id,
            datasource_id=params.datasource_id,
            kind=params.kind,
            status=params.status,
            limit=params.limit,
            offset=params.offset,
        )


def _load_snapshot(watch: EngineRunWatch) -> schemas.EngineRunListSnapshotMessage:
    from modules.engine_runs import service

    token = set_namespace_context(watch.namespace)
    try:
        runs = run_db(
            service.list_engine_runs,
            watch.analysis_id,
            watch.datasource_id,
            watch.kind,
            watch.status,
            watch.limit,
            watch.offset,
        )
    finally:
        reset_namespace(token)
    return schemas.EngineRunListSnapshotMessage(runs=runs)


class EngineRunWatcherRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._watchers: dict[EngineRunWatch, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def add(self, websocket: WebSocket, watch: EngineRunWatch) -> None:
        async with self._lock:
            self._loop = asyncio.get_running_loop()
            self._watchers.setdefault(watch, set()).add(websocket)

    async def discard(self, websocket: WebSocket, watch: EngineRunWatch) -> None:
        async with self._lock:
            sockets = self._watchers.get(watch)
            if sockets is None:
                return
            sockets.discard(websocket)
            if sockets:
                return
            self._watchers.pop(watch, None)

    async def clear(self) -> None:
        async with self._lock:
            self._watchers.clear()
            self._loop = None

    async def snapshot(self, watch: EngineRunWatch) -> schemas.EngineRunListSnapshotMessage:
        return await run_in_threadpool(_load_snapshot, watch)

    async def broadcast(self, namespace: str) -> None:
        async with self._lock:
            items = [(watch, list(sockets)) for watch, sockets in self._watchers.items() if watch.namespace == namespace and sockets]
        stale: dict[EngineRunWatch, list[WebSocket]] = {}
        for watch, sockets in items:
            payload = (await self.snapshot(watch)).model_dump(mode='json')
            for websocket in sockets:
                try:
                    await websocket.send_json(payload)
                except Exception:
                    stale.setdefault(watch, []).append(websocket)
        if not stale:
            return
        async with self._lock:
            for watch, sockets in stale.items():
                current = self._watchers.get(watch)
                if current is None:
                    continue
                for websocket in sockets:
                    current.discard(websocket)
                if current:
                    continue
                self._watchers.pop(watch, None)

    def notify(self, namespace: str) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            loop.create_task(self.broadcast(namespace))
            return
        future = asyncio.run_coroutine_threadsafe(self.broadcast(namespace), loop)
        try:
            future.result(timeout=5)
        except Exception:
            return


registry = EngineRunWatcherRegistry()
