from __future__ import annotations

import asyncio
import logging
from collections import deque

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_manager import ProcessManager
from runtime.config import settings
from runtime.executors import run_control_in_thread
from runtime.live_hubs import VersionHub
from runtime.worker_runtime import RuntimeNamespaceDirectory
from runtime.worker_runtime_client import WorkerRuntimeClient, client_from_env

logger = logging.getLogger(__name__)

# Deletion is event-driven. This is only the lost-notification recovery sweep;
# select one namespace per pass so a worker with no pending deletes never scans
# every tenant in one RPC.
_DATASOURCE_DELETE_RECOVERY_SECONDS = max(
    30.0,
    float(settings.runtime_reconciliation_poll_interval_seconds),
)
datasource_delete_hub: VersionHub[str] = VersionHub()


def worker_runtime_client() -> WorkerRuntimeClient:
    return client_from_env()


async def datasource_delete_loop(
    stop_event: asyncio.Event,
    *,
    manager: ProcessManager,
    namespace_directory: RuntimeNamespaceDirectory | None = None,
) -> None:
    client = worker_runtime_client()
    namespace_directory = namespace_directory or RuntimeNamespaceDirectory(client, refresh_seconds=_DATASOURCE_DELETE_RECOVERY_SECONDS)
    pending_namespaces: deque[str] = deque()
    pending_namespace_set: set[str] = set()
    wake_version = datasource_delete_hub.version()
    try:
        while not stop_event.is_set():
            try:
                current_version = datasource_delete_hub.version()
                for namespace_hint in datasource_delete_hub.payloads_since(wake_version):
                    if isinstance(namespace_hint, str) and namespace_hint and namespace_hint not in pending_namespace_set:
                        pending_namespaces.append(namespace_hint)
                        pending_namespace_set.add(namespace_hint)
                wake_version = current_version

                if pending_namespaces:
                    namespace = pending_namespaces.popleft()
                    pending_namespace_set.discard(namespace)
                else:
                    wake_version, recovery_due = await _wait_for_delete_wakeup_or_recovery(stop_event, wake_version)
                    if not recovery_due:
                        continue
                    recovery_namespace = await namespace_directory.next_namespace()
                    if recovery_namespace is None:
                        continue
                    namespace = recovery_namespace
                handled = await _run_once(manager=manager, client=client, namespace=namespace)
                if handled:
                    # Drain more tombstones in the same namespace before
                    # waiting again, without turning an empty namespace into a
                    # hot loop.
                    pending_namespaces.appendleft(namespace)
                    pending_namespace_set.add(namespace)
                    continue
            except Exception as exc:
                logger.warning("Datasource delete loop iteration failed; will retry: %s", exc)
                await asyncio.sleep(1.0)
                continue
    finally:
        await run_control_in_thread(client.close)


async def _wait_for_delete_wakeup_or_recovery(stop_event: asyncio.Event, wake_version: int) -> tuple[int, bool]:
    wake_task = asyncio.create_task(datasource_delete_hub.wait(last_seen=wake_version))
    stop_task = asyncio.create_task(stop_event.wait())
    recovery_task = asyncio.create_task(asyncio.sleep(_DATASOURCE_DELETE_RECOVERY_SECONDS))
    done, pending = await asyncio.wait(
        {wake_task, stop_task, recovery_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if wake_task in done:
        return wake_task.result(), False
    return datasource_delete_hub.version(), recovery_task in done


async def _run_once(*, manager: ProcessManager, client: WorkerRuntimeClient, namespace: str) -> bool:
    pending_deletes = await run_control_in_thread(client.pending_datasource_deletes, namespace=namespace)
    for pending_delete in pending_deletes:
        if await run_control_in_thread(
            _process_pending_datasource_delete,
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
    client: WorkerRuntimeClient,
) -> bool:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        datasource_id=datasource_id,
        resource_id=datasource_id,
    )
    engine = manager.get_engine(identity, namespace=namespace)
    if engine is not None and engine.current_job_id and engine.is_process_alive():
        return False
    if engine is not None:
        manager.shutdown_engine(identity, namespace=namespace)

    deleted = client.finalize_datasource_delete(namespace=namespace, datasource_id=datasource_id)
    if not deleted:
        return False
    logger.info("Deleted pending datasource %s in namespace %s", datasource_id, namespace)
    return True
