from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core.domain.compute.base import EngineStatusInfo
from backend_core.domain.engine_instances.models import EngineInstanceStatus
from backend_core.persistence.engine_instances.models import EngineInstance


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _copy_json(value: dict[str, object] | None) -> dict[str, object] | None:
    return dict(value) if isinstance(value, dict) else None


def _required_identity_value(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f'engine status is missing {field_name}')
    return value


def _apply_engine_status(row: EngineInstance, *, status: EngineStatusInfo, stamp: datetime) -> None:
    row.process_id = status.process_id
    row.status = EngineInstanceStatus.from_engine_status(status.status, status.current_job_id)
    row.engine_scope = _required_identity_value(status.scope, 'scope')
    row.engine_reuse_policy = _required_identity_value(status.reuse_policy, 'reuse_policy')
    row.datasource_id = status.datasource_id
    row.build_id = status.build_id
    row.current_job_id = status.current_job_id
    row.current_build_id = status.current_build_id
    row.current_engine_run_id = status.current_engine_run_id
    row.resource_config_json = _copy_json(status.resource_config)
    row.effective_resources_json = _copy_json(status.effective_resources)
    row.last_activity_at = _read_dt(status.last_activity) or row.last_activity_at or stamp
    row.last_seen_at = stamp
    row.updated_at = stamp


def upsert_engine_status(session: Session, *, worker_id: str, namespace: str, status: EngineStatusInfo, now: datetime | None = None) -> EngineInstance:
    stamp = now or _utcnow()
    scope = _required_identity_value(status.scope, 'scope')
    instance_id = f'{worker_id}:{namespace}:{scope}:{status.resource_id}'
    row = session.get(EngineInstance, instance_id)
    if row is None:
        row = EngineInstance(
            id=instance_id,
            worker_id=worker_id,
            namespace=namespace,
            analysis_id=status.analysis_id,
            engine_scope=scope,
            engine_reuse_policy=_required_identity_value(status.reuse_policy, 'reuse_policy'),
            datasource_id=status.datasource_id,
            build_id=status.build_id,
            process_id=status.process_id,
            status=EngineInstanceStatus.from_engine_status(status.status, status.current_job_id),
            current_job_id=status.current_job_id,
            current_build_id=status.current_build_id,
            current_engine_run_id=status.current_engine_run_id,
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
    active = {_engine_identity_key(status) for status in statuses}
    for status in statuses:
        upsert_engine_status(session, worker_id=worker_id, namespace=namespace, status=status, now=now)
    _ = mark_namespace_engines_stopped(session, worker_id=worker_id, namespace=namespace, active_engine_identities=active, now=now)


def mark_namespace_engines_stopped(session: Session, *, worker_id: str, namespace: str, active_engine_identities: set[str], now: datetime | None = None) -> int:
    stamp = now or _utcnow()
    stmt = select(EngineInstance).where(EngineInstance.worker_id == worker_id).where(EngineInstance.namespace == namespace)  # type: ignore[arg-type]
    rows = list(session.execute(stmt).scalars().all())
    updated = 0
    for row in rows:
        if _row_identity_key(row) in active_engine_identities:
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
        .order_by(EngineInstance.engine_scope, EngineInstance.analysis_id, EngineInstance.datasource_id, EngineInstance.build_id)  # type: ignore[arg-type]
    )
    return list(session.execute(stmt).scalars().all())


def list_engine_projection(session: Session, *, namespace: str) -> list[EngineInstance]:
    rows = list_engine_instances(session, namespace=namespace)
    latest: dict[str, EngineInstance] = {}
    for row in rows:
        key = _row_identity_key(row)
        current = latest.get(key)
        if current is None:
            latest[key] = row
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
            latest[key] = row
            continue
        if row_activity < current_activity:
            continue
        if row.worker_id < current.worker_id:
            latest[key] = row
    return sorted(latest.values(), key=_row_identity_key)


def latest_namespace_update(session: Session, *, namespace: str) -> datetime | None:
    stmt = select(func.max(EngineInstance.updated_at)).where(EngineInstance.namespace == namespace)  # type: ignore[arg-type]
    value = session.execute(stmt).scalar_one()
    return value if isinstance(value, datetime) else None


def serialize_engine_instance(row: EngineInstance, *, defaults: dict[str, object]) -> dict[str, object]:
    return {
        'analysis_id': row.analysis_id,
        'resource_id': _row_resource_id(row),
        'status': row.status.overview_status,
        'process_id': row.process_id,
        'last_activity': row.last_activity_at.isoformat() if row.last_activity_at is not None else None,
        'current_job_id': row.current_job_id,
        'resource_config': _copy_json(row.resource_config_json),
        'effective_resources': _copy_json(row.effective_resources_json),
        'defaults': defaults,
        'scope': row.engine_scope,
        'reuse_policy': row.engine_reuse_policy,
        'datasource_id': row.datasource_id,
        'build_id': row.build_id,
        'current_build_id': row.current_build_id or row.build_id,
        'current_engine_run_id': row.current_engine_run_id,
    }


def _engine_identity_key(status: EngineStatusInfo) -> str:
    return f'{_required_identity_value(status.scope, "scope")}:{status.resource_id}'


def _row_identity_key(row: EngineInstance) -> str:
    return f'{row.engine_scope}:{_row_resource_id(row)}'


def _row_resource_id(row: EngineInstance) -> str:
    if row.engine_scope == 'datasource_preview' and row.datasource_id:
        return row.datasource_id
    if row.engine_scope == 'build' and row.build_id:
        return row.build_id
    return row.analysis_id


def _read_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
