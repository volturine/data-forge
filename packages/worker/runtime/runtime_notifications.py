from __future__ import annotations

from worker_contracts.build_jobs.live import hub as build_job_hub
from worker_contracts.compute_requests.live import request_hub
from worker_contracts.runtime.events import RuntimePayloadKind


async def handle_runtime_payload(payload: dict[str, object]) -> None:
    kind = RuntimePayloadKind.from_payload(payload)
    if kind == RuntimePayloadKind.JOB:
        build_job_hub.publish()
        return
    if kind == RuntimePayloadKind.COMPUTE_REQUEST:
        request_hub.publish()
