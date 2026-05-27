from __future__ import annotations

import asyncio
import logging

from core import datasource_delete_service
from core.database import get_db
from core.datasource_storage import cleanup_datasource_storage
from core.engine_identity import datasource_preview_engine_key
from core.namespace import reset_namespace, set_namespace_context

from runtime.compute_manager import ProcessManager
from runtime.worker_runtime import runtime_namespaces

logger = logging.getLogger(__name__)

_DATASOURCE_DELETE_POLL_SECONDS = 0.5


async def datasource_delete_loop(stop_event: asyncio.Event, *, manager: ProcessManager) -> None:
    while not stop_event.is_set():
        handled = await _run_once(manager=manager)
        if handled:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_DATASOURCE_DELETE_POLL_SECONDS)
        except asyncio.TimeoutError:
            continue


async def _run_once(*, manager: ProcessManager) -> bool:
    for namespace in runtime_namespaces():
        token = set_namespace_context(namespace)
        try:
            datasource_ids = _pending_datasource_ids()
            for datasource_id in datasource_ids:
                if _process_pending_datasource_delete(datasource_id, manager=manager):
                    return True
        finally:
            reset_namespace(token)
    return False


def _pending_datasource_ids() -> list[str]:
    session_gen = get_db()
    session = next(session_gen)
    try:
        return [datasource.id for datasource in datasource_delete_service.list_pending_deletes(session)]
    finally:
        session.close()
        session_gen.close()


def _process_pending_datasource_delete(datasource_id: str, *, manager: ProcessManager) -> bool:
    engine_key = datasource_preview_engine_key(datasource_id)
    engine = manager.get_engine(engine_key)
    if engine is not None and engine.current_job_id and engine.is_process_alive():
        return False
    if engine is not None:
        manager.shutdown_engine(engine_key)

    session_gen = get_db()
    session = next(session_gen)
    try:
        datasource = datasource_delete_service.get_datasource(session, datasource_id)
        if datasource is None:
            return True
        cleanup_datasource_storage(datasource)
        session.delete(datasource)
        session.commit()
        logger.info("Deleted pending datasource %s", datasource_id)
        return True
    finally:
        session.close()
        session_gen.close()
