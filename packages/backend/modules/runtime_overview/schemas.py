from __future__ import annotations

from datetime import datetime
from typing import Literal

from contracts.engine_instances.models import EngineInstanceStatus
from contracts.runtime_workers.models import RuntimeWorkerKind
from pydantic import BaseModel

RuntimeMode = Literal["single_process", "durable_single_node", "distributed"]


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


class EngineInstanceSummary(BaseModel):
    id: str
    worker_id: str
    namespace: str
    analysis_id: str
    process_id: int | None
    status: EngineInstanceStatus
    current_job_id: str | None
    current_build_id: str | None
    current_engine_run_id: str | None
    last_activity_at: datetime | None
    last_seen_at: datetime


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
    engines: list[EngineInstanceSummary]
    queue: QueueSummary
