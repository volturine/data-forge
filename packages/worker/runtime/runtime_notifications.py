from __future__ import annotations

from runtime.models.build_jobs.live import hub as build_job_hub
from runtime.models.compute_requests.live import request_hub
from runtime.models.runtime.events import RuntimePayloadKind


async def handle_runtime_payload(payload: dict[str, object]) -> None:
    kind = RuntimePayloadKind.from_payload(payload)
    if kind == RuntimePayloadKind.JOB:
        build_job_hub.publish()
        return
    if kind == RuntimePayloadKind.COMPUTE_REQUEST:
        request_hub.publish()
