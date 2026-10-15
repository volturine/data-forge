from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from backend_core import compute_worker_instances_service as compute_worker_instance_service
from backend_core.domain.compute import schemas
from backend_core.websocket import serialize_json


class ComputeWorkerRegistry:
    def __init__(self) -> None:
        self._waiters: dict[str, list[asyncio.Future[str]]] = {}
        self._lock = asyncio.Lock()
        self._version: dict[str, int] = {}
        self._subscribers: Counter[str] = Counter()
        self._snapshot_cache: dict[str, tuple[int, schemas.ComputeWorkersSnapshotMessage]] = {}
        self._snapshot_loads: dict[tuple[str, int], asyncio.Future[tuple[int, schemas.ComputeWorkersSnapshotMessage]]] = {}
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
        pending: list[asyncio.Future[Any]] = [future for items in waiters.values() for future in items]
        pending.extend(snapshot_loads.values())
        pending.extend(serialized_snapshot_loads.values())
        for future in pending:
            if not future.done():
                future.cancel()

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
            if not future.done():
                future.set_result(str(version))

    async def load_snapshot(
        self,
        namespace: str,
        loader: Callable[[], Awaitable[schemas.ComputeWorkersSnapshotMessage]],
    ) -> schemas.ComputeWorkersSnapshotMessage:
        _, snapshot = await self._load_versioned_snapshot(namespace, loader)
        return snapshot

    async def load_serialized_snapshot(
        self,
        namespace: str,
        loader: Callable[[], Awaitable[schemas.ComputeWorkersSnapshotMessage]],
    ) -> tuple[int, str]:
        """Share one encoded status snapshot across every socket at a version."""
        version, snapshot = await self._load_versioned_snapshot(namespace, loader)
        return await self._shared_load(
            lambda: (self._serialized_snapshot_loads, self._serialized_snapshot_cache),
            namespace,
            version,
            lambda: serialize_json(snapshot),
            task_name=f'engine-snapshot-serialize:{namespace}:{version}',
        )

    async def _load_versioned_snapshot(
        self,
        namespace: str,
        loader: Callable[[], Awaitable[schemas.ComputeWorkersSnapshotMessage]],
    ) -> tuple[int, schemas.ComputeWorkersSnapshotMessage]:
        """Load one durable snapshot for all sockets in this API process.

        Engine lifecycle notifications wake every browser socket. Without a
        process-local single-flight, a 50-tab burst turns one durable engine
        projection into 50 database reads. Callers retain the version so an
        update racing the database read cannot be mistaken for its snapshot.
        """
        return await self._shared_load(
            lambda: (self._snapshot_loads, self._snapshot_cache),
            namespace,
            None,
            loader,
            task_name=f'engine-snapshot-load:{namespace}',
        )

    async def _shared_load[T](
        self,
        stores: Callable[[], tuple[dict[tuple[str, int], asyncio.Future[tuple[int, T]]], dict[str, tuple[int, T]]]],
        namespace: str,
        version: int | None,
        produce: Callable[[], Awaitable[T]],
        *,
        task_name: str,
    ) -> tuple[int, T]:
        """Join or start the single in-flight load for ``namespace`` at ``version`` (default: current)."""
        async with self._lock:
            load_version = self._version.get(namespace, 0) if version is None else version
            loads, cache = stores()
            cached = cache.get(namespace)
            if cached is not None and cached[0] == load_version:
                return cached
            load_key = (namespace, load_version)
            load = loads.get(load_key)
            if load is None:
                load = asyncio.get_running_loop().create_future()
                loads[load_key] = load
                asyncio.create_task(self._settle_shared_load(stores, namespace, load_version, load, produce), name=task_name)
        return await asyncio.shield(load)

    async def _settle_shared_load[T](
        self,
        stores: Callable[[], tuple[dict[tuple[str, int], asyncio.Future[tuple[int, T]]], dict[str, tuple[int, T]]]],
        namespace: str,
        version: int,
        load: asyncio.Future[tuple[int, T]],
        produce: Callable[[], Awaitable[T]],
    ) -> None:
        # ``stores`` is re-read after the await because ``clear()`` replaces the dictionaries.
        load_key = (namespace, version)
        try:
            value = await produce()
        except BaseException as exc:
            async with self._lock:
                loads, _cache = stores()
                if loads.get(load_key) is load:
                    loads.pop(load_key, None)
                if not load.done():
                    load.set_exception(exc)
            return

        async with self._lock:
            loads, cache = stores()
            is_current_load = loads.get(load_key) is load
            if is_current_load:
                loads.pop(load_key, None)
            # A notification may have arrived while the load was running.
            # Do not cache an older result under the newer version; the next
            # websocket pass will load the current durable projection.
            if is_current_load and self._version.get(namespace, 0) == version:
                cache[namespace] = (version, value)
            if not load.done():
                load.set_result((version, value))

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
        return str(current) if current > 0 else None


registry = ComputeWorkerRegistry()


def load_compute_worker_snapshot(session, *, namespace: str, defaults: dict[str, object]) -> schemas.ComputeWorkersSnapshotMessage:
    rows = compute_worker_instance_service.list_engine_projection(session, namespace=namespace)
    statuses = [
        schemas.ComputeWorkerStatusSchema.model_validate(compute_worker_instance_service.serialize_compute_worker_instance(row, defaults=defaults))
        for row in rows
    ]
    return schemas.ComputeWorkersSnapshotMessage(compute_workers=statuses, total=len(statuses))
