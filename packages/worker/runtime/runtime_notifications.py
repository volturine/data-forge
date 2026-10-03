from __future__ import annotations

from runtime.datasource_delete_runtime import datasource_delete_hub
from runtime.domain.build_jobs.live import hub as build_job_hub
from runtime.domain.compute_requests.live import ComputeRequestWake, request_hub
from runtime.domain.runtime.events import RuntimePayloadKind
from runtime.storage_cleanup_runtime import storage_cleanup_hub


async def handle_runtime_payload(payload: dict[str, object]) -> None:
    if payload.get("kind") == "storage_cleanup_wakeup":
        namespace = payload.get("namespace")
        if isinstance(namespace, str) and namespace:
            storage_cleanup_hub.publish(namespace)
        return
    kind = RuntimePayloadKind.from_payload(payload)
    if kind == RuntimePayloadKind.JOB:
        namespace = payload.get("namespace")
        build_job_hub.publish(namespace if isinstance(namespace, str) else None)
        return
    if kind == RuntimePayloadKind.COMPUTE_REQUEST:
        request_id = payload.get("request_id")
        namespace = payload.get("namespace")
        compute_kind = payload.get("compute_kind")
        if isinstance(request_id, str) and isinstance(namespace, str) and isinstance(compute_kind, int) and not isinstance(compute_kind, bool):
            request_hub.publish(ComputeRequestWake(request_id=request_id, namespace=namespace, kind=compute_kind))
        return
    if kind == RuntimePayloadKind.COMPUTE_RESPONSE:
        namespace = payload.get("namespace")
        if isinstance(namespace, str) and namespace:
            # A completed request may have left another command queued behind
            # the same engine identity. Wake that namespace immediately; the
            # durable pending-work cursor remains the lost-notification path.
            request_hub.publish(ComputeRequestWake(request_id=None, namespace=namespace, kind=None))
        return
    if kind == RuntimePayloadKind.DATASOURCE_DELETE:
        namespace = payload.get("namespace")
        datasource_delete_hub.publish(namespace if isinstance(namespace, str) else None)
