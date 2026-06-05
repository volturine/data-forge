from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict

from runtime.internal_api import WorkerInternalApiClient, client_from_env
from worker_models.compute.base import EngineStatusInfo


def worker_internal_api_client() -> WorkerInternalApiClient:
    return client_from_env()


def persist_engine_snapshot(
    *,
    worker_id: str,
    namespace: str,
    statuses: list[EngineStatusInfo],
) -> None:
    worker_internal_api_client().persist_engine_snapshot(
        worker_id=worker_id,
        namespace=namespace,
        statuses=[asdict(status) for status in statuses],
    )


def create_snapshot_notifier(
    loop: asyncio.AbstractEventLoop,
    *,
    namespace_provider: Callable[[], str],
    worker_id: str | None = None,
    persist: Callable[[str, list[EngineStatusInfo]], None] | None = None,
) -> Callable[[list[EngineStatusInfo]], None]:
    def notify(statuses: list[EngineStatusInfo]) -> None:
        if loop.is_closed():
            return
        namespace = namespace_provider()
        if persist is not None:
            persist(namespace, list(statuses))
            return
        if worker_id is None:
            raise ValueError("worker_id is required when persist callback is not provided")
        persist_engine_snapshot(worker_id=worker_id, namespace=namespace, statuses=list(statuses))

    return notify
