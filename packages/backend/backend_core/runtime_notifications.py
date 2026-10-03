from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from collections.abc import Awaitable, Callable

from sqlalchemy import tuple_
from sqlmodel import Session, col, select

from backend_core.api_execution_budget import run_api_blocking
from backend_core.compute_response_recovery import response_recovery
from backend_core.database import run_db
from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.engine_live import registry as engine_registry
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.locks.models import ResourceLock
from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB
from backend_core.runtime_outbox_service import OUTBOX_WAKE_KIND
from modules.locks import watchers as lock_watchers
from modules.locks.schemas import LockStatusResponse, LockWebsocketStatusMessage

logger = logging.getLogger(__name__)
_CHAT_EVENT_WAKE_KIND = 'chat_event'
_CHAT_TURN_WAKE_KIND = 'chat_turn'
_PROJECTION_RECOVERY_BATCH_SIZE = 128


def _read_build_sequences(namespace: str, build_ids: list[str]) -> dict[str, int]:
    def read(session: Session) -> dict[str, int]:
        rows = session.exec(select(BuildRun.id, BuildRun.next_event_sequence).where(col(BuildRun.id).in_(build_ids))).all()
        return {build_id: max(sequence - 1, 0) for build_id, sequence in rows}

    token = set_namespace_context(namespace)
    try:
        return run_db(read)
    finally:
        reset_namespace(token)


async def refresh_build_projections() -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    for namespace, build_id in build_hub.active_builds():
        grouped[namespace].append(build_id)
    for namespace, build_ids in grouped.items():
        for offset in range(0, len(build_ids), _PROJECTION_RECOVERY_BATCH_SIZE):
            batch = build_ids[offset : offset + _PROJECTION_RECOVERY_BATCH_SIZE]
            sequences = await run_api_blocking(_read_build_sequences, namespace, batch)
            for build_id, sequence in sequences.items():
                # publish preserves a newer sequence if a notification raced
                # the database read. Never synthesize a replay cursor.
                await build_hub.publish(BuildNotification(namespace=namespace, build_id=build_id, latest_sequence=sequence))
    await build_hub.recover_namespaces()


def _read_lock_statuses(namespace: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], LockStatusResponse]:
    def read(session: Session) -> dict[tuple[str, str], LockStatusResponse]:
        rows = session.exec(select(ResourceLock).where(tuple_(col(ResourceLock.resource_type), col(ResourceLock.resource_id)).in_(keys))).all()
        return {
            (row.resource_type, row.resource_id): LockStatusResponse.model_validate({**row.model_dump(), 'is_expired': False})
            for row in rows
            if not row.is_expired()
        }

    token = set_namespace_context(namespace)
    try:
        return run_db(read)
    finally:
        reset_namespace(token)


async def refresh_lock_projections() -> None:
    grouped: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for (namespace, resource_type, resource_id), version in await lock_watchers.registry.active_keys():
        grouped[namespace].append((resource_type, resource_id, version))
    for namespace, targets in grouped.items():
        for offset in range(0, len(targets), _PROJECTION_RECOVERY_BATCH_SIZE):
            batch = targets[offset : offset + _PROJECTION_RECOVERY_BATCH_SIZE]
            statuses = await run_api_blocking(_read_lock_statuses, namespace, [(resource_type, resource_id) for resource_type, resource_id, _version in batch])
            for resource_type, resource_id, version in batch:
                payload = LockWebsocketStatusMessage(resource_type=resource_type, resource_id=resource_id, lock=statuses.get((resource_type, resource_id)))
                await lock_watchers.refresh_watchers(namespace, resource_type, resource_id, payload, expected_version=version)


async def recover_runtime_notifications(
    *,
    refresh_builds: Callable[[], Awaitable[None]],
    refresh_engines: Callable[[], Awaitable[None]],
    refresh_locks: Callable[[], Awaitable[None]],
) -> None:
    """Recover all API projections after a lost listener connection.

    The process edge supplies durable build/engine/lock refreshes. These are
    mandatory because their websocket consumers have no periodic recovery.
    """
    from modules.chat.store import chat_stream_recovery

    response_recovery.request_poll()
    chat_stream_recovery.wake()
    OUTBOX_WAKE_HUB.publish(None)
    results = await asyncio.gather(refresh_builds(), refresh_engines(), refresh_locks(), return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        raise BaseExceptionGroup('Runtime projection recovery failed', errors)


async def _handle_lock_payload(payload: dict[str, object]) -> None:
    if payload.get('source_pid') == os.getpid():
        return
    namespace = payload.get('namespace')
    resource_type = payload.get('resource_type')
    resource_id = payload.get('resource_id')
    status = payload.get('status')
    if not isinstance(namespace, str) or not isinstance(resource_type, str) or not isinstance(resource_id, str):
        return
    if not isinstance(status, dict):
        return
    await lock_watchers.notify_watchers(namespace, resource_type, resource_id, status)


async def handle_runtime_payload(payload: dict[str, object]) -> None:
    if payload.get('kind') == 'telegram_detection_result':
        request_id = payload.get('request_id')
        if isinstance(request_id, str):
            from modules.telegram.runtime import notify_detection_result

            notify_detection_result(request_id)
        return
    if payload.get('kind') == _CHAT_EVENT_WAKE_KIND:
        session_id = payload.get('session_id')
        sequence = payload.get('sequence')
        if isinstance(session_id, str):
            from modules.chat.store import chat_stream_recovery

            chat_stream_recovery.publish(session_id, sequence if isinstance(sequence, int) else None)
        return
    if payload.get('kind') == _CHAT_TURN_WAKE_KIND:
        return
    if payload.get('kind') == OUTBOX_WAKE_KIND:
        namespace = payload.get('namespace')
        OUTBOX_WAKE_HUB.publish(namespace if isinstance(namespace, str) and namespace else None)
        return
    if payload.get('kind') == 'lock':
        await _handle_lock_payload(payload)
        return
    kind = RuntimePayloadKind.from_payload(payload)
    if kind == RuntimePayloadKind.BUILD:
        namespace = payload.get('namespace')
        build_id = payload.get('build_id')
        latest_sequence = payload.get('latest_sequence')
        if isinstance(namespace, str) and isinstance(build_id, str) and isinstance(latest_sequence, int):
            await build_hub.publish(
                BuildNotification(
                    namespace=namespace,
                    build_id=build_id,
                    latest_sequence=latest_sequence,
                )
            )
        return
    if kind == RuntimePayloadKind.ENGINE:
        namespace = payload.get('namespace')
        if isinstance(namespace, str):
            await engine_registry.publish_namespace(namespace)
        return
    if kind == RuntimePayloadKind.COMPUTE_RESPONSE:
        request_id = payload.get('request_id')
        if isinstance(request_id, str):
            logger.debug('Received compute response wake request_id=%s', request_id)
            await response_recovery.notify(request_id)
