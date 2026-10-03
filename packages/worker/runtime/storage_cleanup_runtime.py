from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from typing import Protocol

from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError
from sqlalchemy import text

from dataforge_protocol import compute_pb2, enums_pb2
from runtime.compute_manager import ProcessManager
from runtime.executors import _run_cleanup_in_thread, run_control_in_thread
from runtime.iceberg_catalog import load_runtime_catalog
from runtime.live_hubs import VersionHub
from runtime.object_store import delete_object, delete_prefix, object_store_storage_options
from runtime.worker_runtime import RuntimeNamespaceDirectory
from runtime.worker_runtime_client import StorageCleanupClaim, async_client_from_env

logger = logging.getLogger(__name__)
storage_cleanup_hub: VersionHub[str] = VersionHub()
_RECOVERY_SECONDS = 5.0
_RID_SLOT_WAIT_SECONDS = 0.05


def _sql_catalog_tables_with_prefix(catalog, *, namespace: str, family_prefix: str) -> list[str]:
    escaped_prefix = family_prefix.replace("/", "//").replace("%", "/%").replace("_", "/_")
    statement = text(
        """
        SELECT table_name
        FROM iceberg_tables
        WHERE catalog_name = :catalog_name
          AND table_namespace = :namespace
          AND table_name LIKE :family_pattern ESCAPE '/'
        ORDER BY table_name
        """
    )
    with catalog.engine.connect() as connection:
        return list(
            connection.execute(
                statement,
                {
                    "catalog_name": catalog.name,
                    "namespace": namespace,
                    "family_pattern": f"{escaped_prefix}%",
                },
            ).scalars()
        )


class StorageCleanupClient(Protocol):
    async def claim_storage_cleanups_async(self, *, namespace: str, limit: int = 1) -> list[StorageCleanupClaim]: ...

    async def authorize_storage_cleanup_async(self, claim: StorageCleanupClaim) -> bool: ...

    async def complete_storage_cleanup_async(self, claim: StorageCleanupClaim, *, error: str | None = None) -> bool: ...


def delete_cleanup_target(claim: StorageCleanupClaim) -> None:
    if claim.catalog_identifier is not None:
        if not claim.catalog_type or not claim.catalog_uri or not claim.warehouse or not claim.catalog_namespace or not claim.catalog_table:
            raise ValueError("Storage cleanup claim is missing its exact Iceberg catalog identity")
        expected_identifier = f"{claim.catalog_namespace}.{claim.catalog_table}"
        if claim.catalog_identifier != expected_identifier:
            raise ValueError("Storage cleanup catalog identifier does not match its structured identity")
        catalog = load_runtime_catalog(
            "local",
            type=claim.catalog_type,
            uri=claim.catalog_uri,
            warehouse=claim.warehouse,
            **object_store_storage_options(),
        )
        identifiers = {claim.catalog_identifier}
        if claim.catalog_family_prefix is not None:
            if claim.catalog_type == "sql":
                table_names = _sql_catalog_tables_with_prefix(
                    catalog,
                    namespace=claim.catalog_namespace,
                    family_prefix=claim.catalog_family_prefix,
                )
            else:
                try:
                    catalog_tables = catalog.list_tables(claim.catalog_namespace)
                except NoSuchNamespaceError:
                    catalog_tables = []
                table_names = []
                for identifier in catalog_tables:
                    if not isinstance(identifier, (tuple, list)) or not identifier or not isinstance(identifier[-1], str):
                        continue
                    if catalog.namespace_to_string(identifier[:-1]) == claim.catalog_namespace:
                        table_names.append(identifier[-1])
            identifiers.update(f"{claim.catalog_namespace}.{table_name}" for table_name in table_names if table_name.startswith(claim.catalog_family_prefix))
        for identifier in sorted(identifiers):
            with contextlib.suppress(NoSuchNamespaceError, NoSuchTableError):
                catalog.drop_table(identifier)
    if claim.is_prefix:
        delete_prefix(claim.url)
        return
    delete_object(claim.url)


async def process_cleanup(manager: ProcessManager, client: StorageCleanupClient, claim: StorageCleanupClaim) -> bool:
    identity = compute_pb2.EngineIdentity(
        scope=enums_pb2.ENGINE_SCOPE_DATASOURCE_PREVIEW,
        reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
        resource_id=claim.resource_id,
        datasource_id=claim.resource_id,
    )
    if await run_control_in_thread(_has_active_datasource_writer, manager, identity, namespace=claim.namespace):
        await client.complete_storage_cleanup_async(claim, error="Datasource writer has not settled")
        return False
    try:
        async with asyncio.timeout(_RID_SLOT_WAIT_SECONDS):
            await manager.await_engine_job_slot(identity, namespace=claim.namespace)
    except TimeoutError:
        await client.complete_storage_cleanup_async(claim, error="Datasource RID slot is busy; retry eligibility")
        return False
    try:
        if await run_control_in_thread(_has_active_datasource_writer, manager, identity, namespace=claim.namespace):
            await client.complete_storage_cleanup_async(claim, error="Datasource writer has not settled")
            return False
        authorized = await client.authorize_storage_cleanup_async(claim)
        if not authorized:
            await client.complete_storage_cleanup_async(
                claim,
                error="Cleanup is referenced, active, or fenced; retry eligibility",
            )
            return False
        error = None
        try:
            await _run_cleanup_in_thread(delete_cleanup_target, claim)
        except Exception as exc:
            # Catalog and object-store exceptions can embed configured URIs.
            # Keep detailed identity in the durable intent, not in logs/errors.
            error = f"{type(exc).__name__}: storage cleanup failed"
            logger.warning("Storage cleanup failed namespace=%s event_id=%s error_type=%s", claim.namespace, claim.event_id, type(exc).__name__)
        return await client.complete_storage_cleanup_async(claim, error=error) and error is None
    finally:
        await run_control_in_thread(manager.release_engine_job_slot, identity, namespace=claim.namespace)


def _has_active_datasource_writer(manager: ProcessManager, identity: compute_pb2.EngineIdentity, *, namespace: str) -> bool:
    info = manager.get_engine_info(identity, namespace=namespace)
    return info is not None and (info.active_reservations > 0 or bool(info.engine.current_job_id))


async def storage_cleanup_loop(
    stop_event: asyncio.Event,
    *,
    manager: ProcessManager,
    namespace_directory: RuntimeNamespaceDirectory | None = None,
    on_progress: Callable[[], None] | None = None,
) -> None:
    client = await async_client_from_env()
    directory = namespace_directory or RuntimeNamespaceDirectory(client, refresh_seconds=_RECOVERY_SECONDS, work_kinds=("storage_cleanup",))
    pending: deque[str] = deque()
    last_seen = storage_cleanup_hub.version()
    next_recovery = 0.0
    in_flight: asyncio.Task[bool | None] | None = None
    namespace: str | None = None

    async def dispatch(target_namespace: str) -> bool | None:
        claims = await client.claim_storage_cleanups_async(namespace=target_namespace, limit=1)
        if not claims:
            return None
        return await process_cleanup(manager, client, claims[0])

    try:
        while not stop_event.is_set():
            if on_progress is not None:
                on_progress()
            current_version = storage_cleanup_hub.version()
            pending.extend(hint for hint in storage_cleanup_hub.payloads_since(last_seen) if isinstance(hint, str) and hint and hint not in pending)
            last_seen = current_version
            if in_flight is not None and in_flight.done():
                next_recovery = asyncio.get_running_loop().time() + _RECOVERY_SECONDS
                try:
                    outcome = in_flight.result()
                    if outcome is True and namespace is not None:
                        pending.append(namespace)
                    if outcome is False:
                        next_recovery = 0.0
                except Exception:
                    logger.warning("Storage cleanup dispatch failed; durable claims remain recoverable", exc_info=True)
                in_flight = None
            if in_flight is None:
                namespace = pending.popleft() if pending else None
                if namespace is None and asyncio.get_running_loop().time() >= next_recovery:
                    namespace = await directory.next_namespace()
                    next_recovery = asyncio.get_running_loop().time() + _RECOVERY_SECONDS
                if namespace is not None:
                    in_flight = asyncio.create_task(dispatch(namespace))
            wake = asyncio.create_task(storage_cleanup_hub.wait(last_seen=last_seen))
            stopped = asyncio.create_task(stop_event.wait())
            pulse = asyncio.create_task(asyncio.sleep(1.0))
            controls = {wake, stopped, pulse}
            try:
                await asyncio.wait(controls | ({in_flight} if in_flight is not None else set()), return_when=asyncio.FIRST_COMPLETED)
            finally:
                for control in controls:
                    if not control.done():
                        control.cancel()
                await asyncio.gather(*controls, return_exceptions=True)
    finally:
        if in_flight is not None:
            if not in_flight.done():
                in_flight.cancel()
            await asyncio.gather(in_flight, return_exceptions=True)
