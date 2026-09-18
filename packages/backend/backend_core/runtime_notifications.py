from __future__ import annotations

import os

from backend_core.domain.build_runs.live import BuildNotification, hub as build_hub
from backend_core.domain.compute_requests.live import response_hub
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.engine_live import registry as engine_registry
from modules.locks import watchers as lock_watchers


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
            response_hub.publish(request_id)
