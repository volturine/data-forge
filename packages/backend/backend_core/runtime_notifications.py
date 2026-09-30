from __future__ import annotations

import logging
import os

from backend_core.compute_response_recovery import response_recovery
from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.engine_live import registry as engine_registry
from backend_core.runtime_outbox_dispatcher import OUTBOX_WAKE_HUB
from backend_core.runtime_outbox_service import OUTBOX_WAKE_KIND
from modules.locks import watchers as lock_watchers

logger = logging.getLogger(__name__)
_CHAT_EVENT_WAKE_KIND = 'chat_event'
_CHAT_TURN_WAKE_KIND = 'chat_turn'


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
