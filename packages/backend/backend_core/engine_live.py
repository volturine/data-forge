from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable

from backend_core import engine_instances_service as engine_instance_service
from backend_core.domain.compute import schemas
from backend_core.websocket import serialize_json


class EngineRegistry:
    def __init__(self) -> None:
        self._waiters: dict[str, list[asyncio.Future[str]]] = {}
        self._lock = asyncio.Lock()
        self._version: dict[str, int] = {}
        self._subscribers: Counter[str] = Counter()
        self._snapshot_cache: dict[str, tuple[int, schemas.EngineListSnapshotMessage]] = {}
        self._snapshot_loads: dict[tuple[str, int], asyncio.Future[tuple[int, schemas.EngineListSnapshotMessage]]] = {}
        self._serialized_snapshot_cache: dict[str, tuple[int, str]] = {}
        self._serialized_snapshot_loads: dict[tuple[str, int], asyncio.Future[tuple[int, str]]] = {}

    async def clear(self) -> None:
        async with self._lock:
            waiters = self._waiters
            self._waiters = {}
            self._version = {}
            self._subscribers.clear()
            snapshot_loads = self._snapshot_loads
            self._snapshot_loads = {}
            self._snapshot_cache = {}
            serialized_snapshot_loads = self._serialized_snapshot_loads
            self._serialized_snapshot_loads = {}
            self._serialized_snapshot_cache = {}
        for items in waiters.values():
            for future in items:
                if future.done():
                    continue
                future.cancel()
        for snapshot_future in snapshot_loads.values():
            if not snapshot_future.done():
                snapshot_future.cancel()
        for serialized_future in serialized_snapshot_loads.values():
            if not serialized_future.done():
                serialized_future.cancel()

    async def wait_for_namespace(self, namespace: str, last_seen: str | None = None) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        async with self._lock:
            current = self._version.get(namespace, 0)
            current_token = str(current)
            if last_seen is not None and current_token != last_seen:
                return current_token
            self._waiters.setdefault(namespace, []).append(future)
        try:
            return await future
        finally:
            await self._discard_waiter(namespace, future)

    async def subscribe(self, namespace: str) -> None:
        async with self._lock:
            self._subscribers[namespace] += 1
            if self._subscribers[namespace] == 1:
                self._version[namespace] = self._version.get(namespace, 0) + 1
                self._snapshot_cache.pop(namespace, None)
                self._serialized_snapshot_cache.pop(namespace, None)

    async def unsubscribe(self, namespace: str) -> None:
        async with self._lock:
            self._subscribers[namespace] -= 1
            if self._subscribers[namespace] <= 0:
                self._subscribers.pop(namespace, None)
                self._snapshot_cache.pop(namespace, None)
                self._serialized_snapshot_cache.pop(namespace, None)

    async def recover_active(self) -> None:
        async with self._lock:
            namespaces = list(self._subscribers)
        for namespace in namespaces:
            await self.publish_namespace(namespace)
            await asyncio.sleep(0)

    async def publish_namespace(self, namespace: str) -> None:
        async with self._lock:
            version = self._version.get(namespace, 0) + 1
            self._version[namespace] = version
            self._snapshot_cache.pop(namespace, None)
            self._serialized_snapshot_cache.pop(namespace, None)
            waiters = self._waiters.pop(namespace, [])
        for future in waiters:
            if future.done():
                continue
            future.set_result(str(version))

    async def publish_snapshot(self, namespace: str, statuses: list[object]) -> None:
        del statuses
        await self.publish_namespace(namespace)

    async def load_snapshot(
        self,
        namespace: str,
        loader: Callable[[], Awaitable[schemas.EngineListSnapshotMessage]],
    ) -> schemas.EngineListSnapshotMessage:
        _, snapshot = await self._load_versioned_snapshot(namespace, loader)
        return snapshot

    async def load_serialized_snapshot(
        self,
        namespace: str,
        loader: Callable[[], Awaitable[schemas.EngineListSnapshotMessage]],
    ) -> tuple[int, str]:
        """Share one encoded status snapshot across every socket at a version."""
        version, snapshot = await self._load_versioned_snapshot(namespace, loader)
        async with self._lock:
            cached = self._serialized_snapshot_cache.get(namespace)
            if cached is not None and cached[0] == version:
                return cached
            load_key = (namespace, version)
            load = self._serialized_snapshot_loads.get(load_key)
            if load is None:
                load = asyncio.get_running_loop().create_future()
                self._serialized_snapshot_loads[load_key] = load
                asyncio.create_task(
                    self._serialize_snapshot(namespace, version, snapshot, load),
                    name=f'engine-snapshot-serialize:{namespace}:{version}',
                )
        return await asyncio.shield(load)

    async def _load_versioned_snapshot(
        self,
        namespace: str,
        loader: Callable[[], Awaitable[schemas.EngineListSnapshotMessage]],
    ) -> tuple[int, schemas.EngineListSnapshotMessage]:
        """Load one durable snapshot for all sockets in this API process.

        Engine lifecycle notifications wake every browser socket. Without a
        process-local single-flight, a 50-tab burst turns one durable engine
        projection into 50 database reads. Callers retain the version so an
        update racing the database read cannot be mistaken for its snapshot.
        """
        async with self._lock:
            version = self._version.get(namespace, 0)
            cached = self._snapshot_cache.get(namespace)
            if cached is not None and cached[0] == version:
                return cached
            load_key = (namespace, version)
            load = self._snapshot_loads.get(load_key)
            if load is None:
                load = asyncio.get_running_loop().create_future()
                self._snapshot_loads[load_key] = load
                asyncio.create_task(
                    self._load_snapshot(namespace, version, load, loader),
                    name=f'engine-snapshot-load:{namespace}',
                )
        return await asyncio.shield(load)

    async def _load_snapshot(
        self,
        namespace: str,
        version: int,
        load: asyncio.Future[tuple[int, schemas.EngineListSnapshotMessage]],
        loader: Callable[[], Awaitable[schemas.EngineListSnapshotMessage]],
    ) -> None:
        try:
            snapshot = await loader()
        except BaseException as exc:
            async with self._lock:
                load_key = (namespace, version)
                if self._snapshot_loads.get(load_key) is load:
                    self._snapshot_loads.pop(load_key, None)
                if not load.done():
                    load.set_exception(exc)
            return

        async with self._lock:
            load_key = (namespace, version)
            is_current_load = self._snapshot_loads.get(load_key) is load
            if is_current_load:
                self._snapshot_loads.pop(load_key, None)
            # A notification may have arrived while the query was running.
            # Do not cache an older query under the newer version; the next
            # websocket pass will load the current durable projection.
            if is_current_load and self._version.get(namespace, 0) == version:
                self._snapshot_cache[namespace] = (version, snapshot)
            if not load.done():
                load.set_result((version, snapshot))

    async def _serialize_snapshot(
        self,
        namespace: str,
        version: int,
        snapshot: schemas.EngineListSnapshotMessage,
        load: asyncio.Future[tuple[int, str]],
    ) -> None:
        try:
            serialized = await serialize_json(snapshot)
        except BaseException as exc:
            async with self._lock:
                load_key = (namespace, version)
                if self._serialized_snapshot_loads.get(load_key) is load:
                    self._serialized_snapshot_loads.pop(load_key, None)
                if not load.done():
                    load.set_exception(exc)
            return

        async with self._lock:
            load_key = (namespace, version)
            is_current_load = self._serialized_snapshot_loads.get(load_key) is load
            if is_current_load:
                self._serialized_snapshot_loads.pop(load_key, None)
            if is_current_load and self._version.get(namespace, 0) == version:
                self._serialized_snapshot_cache[namespace] = (version, serialized)
            if not load.done():
                load.set_result((version, serialized))

    async def _discard_waiter(self, namespace: str, future: asyncio.Future[str]) -> None:
        async with self._lock:
            current = self._waiters.get(namespace)
            if current is None:
                return
            next_waiters = [item for item in current if item is not future and not item.done()]
            if next_waiters:
                self._waiters[namespace] = next_waiters
                return
            self._waiters.pop(namespace, None)

    async def current_version(self, namespace: str) -> str | None:
        async with self._lock:
            current = self._version.get(namespace, 0)
            if current <= 0:
                return None
            return str(current)


registry = EngineRegistry()


def load_engine_snapshot(session, *, namespace: str, defaults: dict[str, object]) -> schemas.EngineListSnapshotMessage:
    rows = engine_instance_service.list_engine_projection(session, namespace=namespace)
    statuses = [schemas.EngineStatusSchema.model_validate(engine_instance_service.serialize_engine_instance(row, defaults=defaults)) for row in rows]
    return schemas.EngineListSnapshotMessage(engines=statuses, total=len(statuses))
