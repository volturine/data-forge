from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from contracts.compute.base import EngineStatusInfo
from contracts.engine_instances.models import EngineInstance, EngineInstanceStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _copy_json(value: dict[str, object] | None) -> dict[str, object] | None:
    return dict(value) if isinstance(value, dict) else None


def _apply_engine_status(row: EngineInstance, *, status: EngineStatusInfo, stamp: datetime) -> None:
    row.process_id = status.process_id
    row.status = EngineInstanceStatus.from_engine_status(status.status, status.current_job_id)
    row.current_job_id = status.current_job_id
    row.resource_config_json = _copy_json(status.resource_config)
    row.effective_resources_json = _copy_json(status.effective_resources)
    row.last_activity_at = _read_dt(status.last_activity) or row.last_activity_at or stamp
    row.last_seen_at = stamp
    row.updated_at = stamp


def upsert_engine_status(session: Session, *, worker_id: str, namespace: str, status: EngineStatusInfo, now: datetime | None = None) -> EngineInstance:
    stamp = now or _utcnow()
    instance_id = f'{worker_id}:{namespace}:{status.analysis_id}'
    row = session.get(EngineInstance, instance_id)
    if row is None:
        row = EngineInstance(
            id=instance_id,
            worker_id=worker_id,
            namespace=namespace,
            analysis_id=status.analysis_id,
            process_id=status.process_id,
            status=EngineInstanceStatus.from_engine_status(status.status, status.current_job_id),
            current_job_id=status.current_job_id,
            current_build_id=None,
            current_engine_run_id=None,
            resource_config_json=_copy_json(status.resource_config),
            effective_resources_json=_copy_json(status.effective_resources),
            last_activity_at=_read_dt(status.last_activity) or stamp,
            last_seen_at=stamp,
            updated_at=stamp,
        )
    else:
        _apply_engine_status(row, status=status, stamp=stamp)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        row = session.get(EngineInstance, instance_id)
        if row is None:
            raise
        _apply_engine_status(row, status=status, stamp=stamp)
        session.add(row)
        session.commit()
    session.refresh(row)
    return row


def persist_engine_snapshot(session: Session, *, worker_id: str, namespace: str, statuses: list[EngineStatusInfo], now: datetime | None = None) -> None:
    active = {status.analysis_id for status in statuses}
    for status in statuses:
        upsert_engine_status(session, worker_id=worker_id, namespace=namespace, status=status, now=now)
    _ = mark_namespace_engines_stopped(session, worker_id=worker_id, namespace=namespace, active_analysis_ids=active, now=now)


def mark_namespace_engines_stopped(session: Session, *, worker_id: str, namespace: str, active_analysis_ids: set[str], now: datetime | None = None) -> int:
    stamp = now or _utcnow()
    stmt = select(EngineInstance).where(EngineInstance.worker_id == worker_id).where(EngineInstance.namespace == namespace)  # type: ignore[arg-type]
    rows = list(session.execute(stmt).scalars().all())
    updated = 0
    for row in rows:
        if row.analysis_id in active_analysis_ids:
            continue
        if row.status == EngineInstanceStatus.STOPPED:
            continue
        row.status = EngineInstanceStatus.STOPPED
        row.current_job_id = None
        row.current_build_id = None
        row.current_engine_run_id = None
        row.last_seen_at = stamp
        row.updated_at = stamp
        session.add(row)
        updated += 1
    if updated:
        session.commit()
    return updated


def list_engine_instances(session: Session, *, namespace: str) -> list[EngineInstance]:
    active = [status for status in EngineInstanceStatus if status.is_active]
    stmt = (
        select(EngineInstance)
        .where(EngineInstance.namespace == namespace)  # type: ignore[arg-type]
        .where(EngineInstance.status.in_(active))  # type: ignore[attr-defined]
        .order_by(EngineInstance.analysis_id)  # type: ignore[arg-type]
    )
    return list(session.execute(stmt).scalars().all())


def list_engine_projection(session: Session, *, namespace: str) -> list[EngineInstance]:
    rows = list_engine_instances(session, namespace=namespace)
    latest: dict[str, EngineInstance] = {}
    for row in rows:
        current = latest.get(row.analysis_id)
        if current is None:
            latest[row.analysis_id] = row
            continue
        current_seen = current.last_seen_at or current.updated_at
        row_seen = row.last_seen_at or row.updated_at
        if row_seen > current_seen:
            latest[row.analysis_id] = row
            continue
        if row_seen < current_seen:
            continue
        current_activity = current.last_activity_at or current.updated_at
        row_activity = row.last_activity_at or row.updated_at
        if row_activity > current_activity:
            latest[row.analysis_id] = row
            continue
        if row_activity < current_activity:
            continue
        if row.worker_id < current.worker_id:
            latest[row.analysis_id] = row
    return sorted(latest.values(), key=lambda row: row.analysis_id)


def latest_namespace_update(session: Session, *, namespace: str) -> datetime | None:
    stmt = select(func.max(EngineInstance.updated_at)).where(EngineInstance.namespace == namespace)  # type: ignore[arg-type]
    value = session.execute(stmt).scalar_one()
    return value if isinstance(value, datetime) else None


def serialize_engine_instance(row: EngineInstance, *, defaults: dict[str, object]) -> dict[str, object]:
    return {
        'analysis_id': row.analysis_id,
        'status': row.status.overview_status,
        'process_id': row.process_id,
        'last_activity': row.last_activity_at.isoformat() if row.last_activity_at is not None else None,
        'current_job_id': row.current_job_id,
        'resource_config': _copy_json(row.resource_config_json),
        'effective_resources': _copy_json(row.effective_resources_json),
        'defaults': defaults,
    }


def _read_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
