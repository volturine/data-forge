from __future__ import annotations

from contracts.build_runs.live import BuildNotification
from contracts.build_runs.live import hub as build_hub
from contracts.compute_requests.live import response_hub
from contracts.runtime.ipc import RuntimePayloadKind

from backend_core.engine_live import registry as engine_registry


async def handle_runtime_payload(payload: dict[str, object]) -> None:
    kind = RuntimePayloadKind.from_payload(payload)
    if kind == RuntimePayloadKind.BUILD:
        namespace = payload.get("namespace")
        build_id = payload.get("build_id")
        latest_sequence = payload.get("latest_sequence")
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
        namespace = payload.get("namespace")
        if isinstance(namespace, str):
            await engine_registry.publish_namespace(namespace)
        return
    if kind == RuntimePayloadKind.COMPUTE_RESPONSE:
        request_id = payload.get("request_id")
        if isinstance(request_id, str):
            response_hub.publish(request_id)
