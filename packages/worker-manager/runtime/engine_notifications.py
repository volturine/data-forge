from __future__ import annotations

import asyncio
from collections.abc import Callable

from contracts.compute.base import EngineStatusInfo
from contracts.runtime import ipc as runtime_ipc
from core import engine_instances_service as engine_instance_service
from core.database import run_settings_db
from core.namespace import get_namespace


def persist_engine_snapshot(
    *,
    worker_id: str,
    namespace: str,
    statuses: list[EngineStatusInfo],
) -> None:
    def _write(session) -> None:
        engine_instance_service.persist_engine_snapshot(
            session,
            worker_id=worker_id,
            namespace=namespace,
            statuses=statuses,
        )

    run_settings_db(_write)
    runtime_ipc.notify_api_engine(namespace)


def create_snapshot_notifier(
    loop: asyncio.AbstractEventLoop,
    *,
    worker_id: str | None = None,
    persist: Callable[[str, list[EngineStatusInfo]], None] | None = None,
) -> Callable[[list[EngineStatusInfo]], None]:
    def notify(statuses: list[EngineStatusInfo]) -> None:
        if loop.is_closed():
            return
        namespace = get_namespace()
        if persist is not None:
            persist(namespace, list(statuses))
            return
        if worker_id is None:
            raise ValueError("worker_id is required when persist callback is not provided")
        persist_engine_snapshot(worker_id=worker_id, namespace=namespace, statuses=list(statuses))

    return notify
