from __future__ import annotations

import socket
from datetime import UTC, datetime

from contracts.build_jobs.models import BuildJob, BuildJobStatus
from contracts.engine_instances.models import EngineInstance
from contracts.runtime_workers.models import RuntimeWorker, RuntimeWorkerKind
from core import runtime_workers_service
from core.config import settings
from core.database import run_db, run_settings_db, supports_distributed_runtime
from core.namespace import list_namespaces, reset_namespace, set_namespace_context
from sqlmodel import Session, select

from . import schemas


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    return value.replace(tzinfo=UTC)


def _age_seconds(value: datetime, *, now: datetime | None = None) -> float:
    stamp = now or _utcnow()
    return max((stamp - _as_utc(value)).total_seconds(), 0.0)


def runtime_mode() -> schemas.RuntimeMode:
    if supports_distributed_runtime():
        return "distributed"
    if settings.embedded_build_worker_enabled:
        return "single_process"
    return "durable_single_node"


def api_process(worker_id: str | None) -> schemas.ApiProcessSummary:
    return schemas.ApiProcessSummary(
        worker_id=worker_id,
        pid=0 if worker_id is None else int(worker_id.split(":")[-1]),
        hostname=socket.gethostname(),
        version=settings.app_version,
    )


def list_worker_summaries(session: Session) -> list[schemas.RuntimeWorkerSummary]:
    now = _utcnow()
    stmt = select(RuntimeWorker).order_by(RuntimeWorker.kind, RuntimeWorker.started_at)  # type: ignore[arg-type]
    rows = list(session.execute(stmt).scalars().all())
    return [
        schemas.RuntimeWorkerSummary(
            id=row.id,
            kind=row.kind,
            hostname=row.hostname,
            pid=row.pid,
            capacity=row.capacity,
            active_jobs=row.active_jobs,
            started_at=row.started_at,
            last_heartbeat_at=row.last_heartbeat_at,
            heartbeat_age_seconds=row.heartbeat_age_seconds(now=now),
            stopped_at=row.stopped_at,
        )
        for row in rows
    ]


def list_engine_summaries(session: Session) -> list[schemas.EngineInstanceSummary]:
    stmt = select(EngineInstance).order_by(EngineInstance.namespace, EngineInstance.analysis_id)  # type: ignore[arg-type]
    rows = list(session.execute(stmt).scalars().all())
    return [
        schemas.EngineInstanceSummary(
            id=row.id,
            worker_id=row.worker_id,
            namespace=row.namespace,
            analysis_id=row.analysis_id,
            process_id=row.process_id,
            status=row.status,
            current_job_id=row.current_job_id,
            current_build_id=row.current_build_id,
            current_engine_run_id=row.current_engine_run_id,
            last_activity_at=row.last_activity_at,
            last_seen_at=row.last_seen_at,
        )
        for row in rows
    ]


def queue_summary() -> schemas.QueueSummary:
    names = [
        settings.default_namespace,
        *[name for name in list_namespaces() if name != settings.default_namespace],
    ]
    seen: set[str] = set()
    items: list[schemas.QueueNamespaceSummary] = []
    for namespace in names:
        if namespace in seen:
            continue
        seen.add(namespace)
        items.append(_queue_namespace_summary(namespace))
    totals = _queue_totals(items)
    return schemas.QueueSummary(namespaces=items, totals=totals)


def _queue_namespace_summary(namespace: str) -> schemas.QueueNamespaceSummary:
    reclaimable_worker_ids = run_settings_db(
        runtime_workers_service.reclaimable_worker_ids,
        kind=RuntimeWorkerKind.BUILD_WORKER,
    )
    token = set_namespace_context(namespace)
    try:
        return run_db(
            _read_queue_namespace_summary,
            namespace=namespace,
            reclaimable_worker_ids=reclaimable_worker_ids,
        )
    finally:
        reset_namespace(token)


def _read_queue_namespace_summary(
    session: Session,
    *,
    namespace: str,
    reclaimable_worker_ids: set[str],
) -> schemas.QueueNamespaceSummary:
    now = _utcnow()
    stmt = select(BuildJob).where(BuildJob.namespace == namespace)  # type: ignore[arg-type]
    rows = list(session.execute(stmt).scalars().all())
    queued = [row for row in rows if row.status == BuildJobStatus.QUEUED]
    oldest = min(queued, key=lambda row: row.created_at, default=None)
    active_rows = [row for row in rows if row.status.is_active]
    orphaned = [row for row in active_rows if row.is_orphaned(reclaimable_worker_ids)]
    age = None if oldest is None else oldest.age_seconds(now=now)
    return schemas.QueueNamespaceSummary(
        namespace=namespace,
        queued=len(queued),
        running=len(active_rows) - len(orphaned),
        orphaned=len(orphaned),
        oldest_queued_at=oldest.created_at if oldest is not None else None,
        oldest_queued_age_seconds=age,
    )


def _queue_totals(
    items: list[schemas.QueueNamespaceSummary],
) -> schemas.QueueTotalsSummary:
    oldest = min((item.oldest_queued_at for item in items if item.oldest_queued_at is not None), default=None)
    now = _utcnow()
    age = None if oldest is None else _age_seconds(oldest, now=now)
    return schemas.QueueTotalsSummary(
        queued=sum(item.queued for item in items),
        running=sum(item.running for item in items),
        orphaned=sum(item.orphaned for item in items),
        oldest_queued_at=oldest,
        oldest_queued_age_seconds=age,
    )
