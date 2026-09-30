from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core.domain.compute.base import EngineStatusInfo
from backend_core.domain.engine_instances.models import EngineInstanceStatus
from backend_core.json_utils import copy_json_object
from backend_core.persistence.engine_instances.models import EngineInstance
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import utc_now as _utcnow


def _required_identity_value(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f'engine status is missing {field_name}')
    return value


def _lock_engine_snapshot(session: Session, *, worker_id: str, namespace: str) -> None:
    bind = session.get_bind()
    if getattr(getattr(bind, 'dialect', None), 'name', None) != 'postgresql':
        return
    digest = sha256(f'dataforge:engine-snapshot:{worker_id}:{namespace}'.encode()).digest()
    key = int.from_bytes(digest[:8], byteorder='big', signed=True)
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def _apply_engine_status(row: EngineInstance, *, status: EngineStatusInfo, stamp: datetime) -> None:
    projection = {
        'container_id': status.container_id,
        'image_digest': status.image_digest,
        'termination_reason': status.termination_reason,
        'exit_code': status.exit_code,
        'oom_killed': status.oom_killed,
        'supervisor_id': status.supervisor_id,
        'owner_id': status.owner_id,
        'status': (
            EngineInstanceStatus.require(status.lifecycle_status)
            if status.lifecycle_status
            else EngineInstanceStatus.from_engine_status(status.status, status.current_job_id)
        ),
        'engine_scope': _required_identity_value(status.scope, 'scope'),
        'engine_reuse_policy': _required_identity_value(status.reuse_policy, 'reuse_policy'),
        'datasource_id': status.datasource_id,
        'build_id': status.build_id,
        'current_job_id': status.current_job_id,
        'current_build_id': status.current_build_id,
        'current_engine_run_id': status.current_engine_run_id,
        'resource_config_json': copy_json_object(status.resource_config),
        'effective_resources_json': copy_json_object(status.effective_resources),
        'last_activity_at': _read_dt(status.last_activity) or row.last_activity_at or stamp,
    }
    changed = {field: value for field, value in projection.items() if getattr(row, field, None) != value}
    if not changed:
        return
    for field, value in changed.items():
        setattr(row, field, value)
    row.last_seen_at = stamp
    row.updated_at = stamp


def _upsert_engine_status(
    session: Session,
    *,
    worker_id: str,
    namespace: str,
    status: EngineStatusInfo,
    now: datetime | None = None,
    commit: bool,
) -> EngineInstance:
    if commit:
        _lock_engine_snapshot(session, worker_id=worker_id, namespace=namespace)
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
            container_id=status.container_id,
            image_digest=status.image_digest,
            termination_reason=status.termination_reason,
            exit_code=status.exit_code,
            oom_killed=status.oom_killed,
            supervisor_id=status.supervisor_id,
            owner_id=status.owner_id,
            status=EngineInstanceStatus.require(status.lifecycle_status)
            if status.lifecycle_status
            else EngineInstanceStatus.from_engine_status(status.status, status.current_job_id),
            current_job_id=status.current_job_id,
            current_build_id=status.current_build_id,
            current_engine_run_id=status.current_engine_run_id,
            resource_config_json=copy_json_object(status.resource_config),
            effective_resources_json=copy_json_object(status.effective_resources),
            last_activity_at=_read_dt(status.last_activity) or stamp,
            last_seen_at=stamp,
            updated_at=stamp,
        )
    else:
        _apply_engine_status(row, status=status, stamp=stamp)
    session.add(row)
    if not commit:
        return row
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


def upsert_engine_status(session: Session, *, worker_id: str, namespace: str, status: EngineStatusInfo, now: datetime | None = None) -> EngineInstance:
    """Persist one engine projection for callers that own a single update."""
    return _upsert_engine_status(session, worker_id=worker_id, namespace=namespace, status=status, now=now, commit=True)


def persist_engine_snapshot(session: Session, *, worker_id: str, namespace: str, statuses: list[EngineStatusInfo], now: datetime | None = None) -> None:
    """Persist one namespace snapshot in one transaction.

    Engine lifecycle changes can include several identities at once. Committing
    each row independently turns one projection update into a serial database
    round trip per engine and lets snapshot traffic starve lease/control RPCs.
    The coordinator is the fenced owner, so the whole namespace projection can
    be written atomically and observed as one state transition.
    """
    for attempt in range(2):
        _lock_engine_snapshot(session, worker_id=worker_id, namespace=namespace)
        try:
            _persist_engine_snapshot_locked(
                session,
                worker_id=worker_id,
                namespace=namespace,
                statuses=statuses,
                now=now,
            )
            return
        except IntegrityError:
            # PostgreSQL snapshots are fenced by the advisory lock. Retrying
            # once also handles concurrent inserts on SQLite, where that lock
            # is intentionally unavailable.
            session.rollback()
            if attempt:
                raise


def _persist_engine_snapshot_locked(
    session: Session,
    *,
    worker_id: str,
    namespace: str,
    statuses: list[EngineStatusInfo],
    now: datetime | None,
) -> None:
    stamp = now or _utcnow()
    active_by_id: dict[str, EngineStatusInfo] = {}
    for status in statuses:
        scope = _required_identity_value(status.scope, 'scope')
        resource_id = _required_identity_value(status.resource_id, 'resource_id')
        active_by_id[f'{worker_id}:{namespace}:{scope}:{resource_id}'] = status

    existing = {}
    if active_by_id:
        existing = {row.id: row for row in session.exec(select(EngineInstance).where(col(EngineInstance.id).in_(active_by_id)))}

    for instance_id, status in active_by_id.items():
        row = existing.get(instance_id)
        if row is None:
            scope = _required_identity_value(status.scope, 'scope')
            row = EngineInstance(
                id=instance_id,
                worker_id=worker_id,
                namespace=namespace,
                analysis_id=status.analysis_id,
                engine_scope=scope,
                engine_reuse_policy=_required_identity_value(status.reuse_policy, 'reuse_policy'),
                last_seen_at=stamp,
                updated_at=stamp,
            )
        _apply_engine_status(row, status=status, stamp=stamp)
        session.add(row)

    stop_engines = (
        update(EngineInstance)
        .where(col(EngineInstance.worker_id) == worker_id)
        .where(col(EngineInstance.namespace) == namespace)
        .where(col(EngineInstance.status) != EngineInstanceStatus.STOPPED.value)
    )
    if active_by_id:
        stop_engines = stop_engines.where(col(EngineInstance.id).not_in(active_by_id))
    session.execute(
        stop_engines.values(
            status=EngineInstanceStatus.STOPPED.value,
            current_job_id=None,
            current_build_id=None,
            current_engine_run_id=None,
            last_seen_at=stamp,
            updated_at=stamp,
        ).execution_options(synchronize_session=False)
    )
    session.commit()


def mark_namespace_engines_stopped(
    session: Session,
    *,
    worker_id: str,
    namespace: str,
    active_engine_identities: set[str],
    now: datetime | None = None,
    commit: bool = True,
) -> int:
    stamp = now or _utcnow()
    stmt = select(EngineInstance).where(sa(EngineInstance.worker_id == worker_id)).where(sa(EngineInstance.namespace == namespace))
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
    if updated and commit:
        session.commit()
    return updated


def list_engine_instances(session: Session, *, namespace: str) -> list[EngineInstance]:
    active = [status for status in EngineInstanceStatus.members() if status.is_active]
    stmt = (
        select(EngineInstance)
        .where(sa(EngineInstance.namespace == namespace))
        .where(col(EngineInstance.status).in_(active))
        .order_by(sa(EngineInstance.engine_scope), sa(EngineInstance.analysis_id), sa(EngineInstance.datasource_id), sa(EngineInstance.build_id))
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
            latest[key] = row
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
    stmt = select(func.max(EngineInstance.updated_at)).where(sa(EngineInstance.namespace == namespace))
    value = session.execute(stmt).scalar_one()
    return value if isinstance(value, datetime) else None


def serialize_engine_instance(row: EngineInstance, *, defaults: dict[str, object]) -> dict[str, object]:
    return {
        'analysis_id': row.analysis_id or None,
        'resource_id': _row_resource_id(row),
        'status': row.status_kind().overview_status,
        'container_id': row.container_id,
        'image_digest': row.image_digest,
        'lifecycle_status': row.status_kind().value,
        'termination_reason': row.termination_reason,
        'exit_code': row.exit_code,
        'oom_killed': row.oom_killed,
        'supervisor_id': row.supervisor_id,
        'owner_id': row.owner_id,
        'last_activity': row.last_activity_at.isoformat() if row.last_activity_at is not None else None,
        'current_job_id': row.current_job_id,
        'resource_config': copy_json_object(row.resource_config_json),
        'effective_resources': copy_json_object(row.effective_resources_json),
        'defaults': defaults,
        'scope': row.engine_scope,
        'reuse_policy': row.engine_reuse_policy,
        'datasource_id': row.datasource_id,
        'build_id': row.build_id,
        'current_build_id': row.current_build_id or row.build_id,
        'current_engine_run_id': row.current_engine_run_id,
    }


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
