from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict

from runtime.domain.compute.base import EngineStatusInfo
from runtime.worker_runtime_client import WorkerRuntimeClient, client_from_env

logger = logging.getLogger(__name__)


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


def persist_engine_snapshot(
    *,
    worker_id: str,
    namespace: str,
    statuses: list[EngineStatusInfo],
) -> None:
    with worker_runtime_client() as client:
        client.persist_engine_snapshot(
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
        try:
            persist_engine_snapshot(worker_id=worker_id, namespace=namespace, statuses=list(statuses))
        except Exception:
            # Engine state is also recoverable from the worker/runtime APIs. A
            # transient API worker replacement must not turn a successful
            # engine start into a failed compute request merely because its
            # live projection could not be persisted.
            logger.warning("Failed to publish engine snapshot for namespace %s", namespace, exc_info=True)

    return notify
