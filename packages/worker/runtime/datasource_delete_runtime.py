from __future__ import annotations

import asyncio
import logging

from runtime.compute_manager import ProcessManager
from runtime.engine_identity import datasource_preview_engine_identity
from runtime.internal_api import WorkerInternalApiClient, client_from_env

logger = logging.getLogger(__name__)

_DATASOURCE_DELETE_POLL_SECONDS = 0.5


def worker_internal_api_client() -> WorkerInternalApiClient:
    return client_from_env()


async def datasource_delete_loop(stop_event: asyncio.Event, *, manager: ProcessManager) -> None:
    while not stop_event.is_set():
        try:
            handled = await _run_once(manager=manager)
            if handled:
                continue
        except Exception as exc:
            logger.warning("Datasource delete loop iteration failed; will retry: %s", exc)
            await asyncio.sleep(1.0)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_DATASOURCE_DELETE_POLL_SECONDS)
        except asyncio.TimeoutError:
            continue


async def _run_once(*, manager: ProcessManager) -> bool:
    client = worker_internal_api_client()
    for pending_delete in client.pending_datasource_deletes():
        if _process_pending_datasource_delete(
            pending_delete.datasource_id,
            namespace=pending_delete.namespace,
            manager=manager,
            client=client,
        ):
            return True
    return False


def _process_pending_datasource_delete(
    datasource_id: str,
    *,
    namespace: str,
    manager: ProcessManager,
    client: WorkerInternalApiClient,
) -> bool:
    identity = datasource_preview_engine_identity(datasource_id)
    engine = manager.get_engine(identity, namespace=namespace)
    if engine is not None and engine.current_job_id and engine.is_process_alive():
        return False
    if engine is not None:
        manager.shutdown_engine(identity, namespace=namespace)

    deleted = client.finalize_datasource_delete(namespace=namespace, datasource_id=datasource_id)
    if deleted:
        logger.info("Deleted pending datasource %s in namespace %s", datasource_id, namespace)
    return True
