from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend_core.domain.compute.schemas import ComputeWorkerReusePolicy, ComputeWorkerScope
from backend_core.domain.compute_worker_instances.models import ComputeWorkerInstanceStatus
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind

RuntimeMode = Literal['durable_single_node', 'distributed']


class ApiProcessSummary(BaseModel):
    worker_id: str | None
    pid: int
    hostname: str
    version: str


class RuntimeWorkerSummary(BaseModel):
    id: str
    kind: RuntimeWorkerKind
    hostname: str
    pid: int
    capacity: int
    active_jobs: int
    started_at: datetime
    last_heartbeat_at: datetime
    heartbeat_age_seconds: float
    stopped_at: datetime | None


class ComputeWorkerInstanceSummary(BaseModel):
    id: str
    worker_id: str
    namespace: str
    analysis_id: str
    resource_id: str
    container_id: str | None
    image_digest: str | None
    termination_reason: str | None
    exit_code: int | None
    oom_killed: bool | None
    supervisor_id: str | None
    owner_id: str | None
    docker_host: str | None = None
    status: ComputeWorkerInstanceStatus
    current_job_id: str | None
    current_build_id: str | None
    current_compute_worker_run_id: str | None
    last_activity_at: datetime | None
    last_seen_at: datetime
    scope: ComputeWorkerScope | None = None
    reuse_policy: ComputeWorkerReusePolicy | None = None
    datasource_id: str | None = None
    build_id: str | None = None


class QueueNamespaceSummary(BaseModel):
    namespace: str
    queued: int
    running: int
    orphaned: int
    oldest_queued_at: datetime | None
    oldest_queued_age_seconds: float | None


class QueueTotalsSummary(BaseModel):
    queued: int
    running: int
    orphaned: int
    oldest_queued_at: datetime | None
    oldest_queued_age_seconds: float | None


class QueueSummary(BaseModel):
    namespaces: list[QueueNamespaceSummary]
    totals: QueueTotalsSummary


class RuntimeOverviewResponse(BaseModel):
    mode: RuntimeMode
    api: ApiProcessSummary
    workers: list[RuntimeWorkerSummary]
    compute_workers: list[ComputeWorkerInstanceSummary]
    queue: QueueSummary
