import time
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import func, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core import runtime_ipc, runtime_workers_service
from backend_core.domain.compute.base import ComputeWorkerStatusInfo
from backend_core.domain.engine_instances.models import EngineInstanceStatus
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.json_utils import copy_json_object
from backend_core.persistence.compute_worker_instances.models import ComputeWorkerInstance
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import utc_now as _utcnow

_snapshot_phase_clock = time.perf_counter
_ENGINE_STATUS_PROJECTION_FIELDS = (
    'container_id',
    'image_digest',
    'termination_reason',
    'exit_code',
    'oom_killed',
    'supervisor_id',
    'owner_id',
    'status',
    'compute_worker_scope',
    'compute_worker_reuse_policy',
    'datasource_id',
    'build_id',
    'current_job_id',
    'current_build_id',
    'current_compute_worker_run_id',
    'resource_config_json',
    'effective_resources_json',
    'last_activity_at',
)


def _start_snapshot_phase(phase_timings: dict[str, float] | None) -> float | None:
    return _snapshot_phase_clock() if phase_timings is not None else None


def _finish_snapshot_phase(phase_timings: dict[str, float] | None, name: str, started: float | None) -> None:
    if phase_timings is None or started is None:
        return
    elapsed_ms = (_snapshot_phase_clock() - started) * 1000
    phase_timings[name] = phase_timings.get(name, 0.0) + elapsed_ms


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


def _engine_status_projection(*, status: ComputeWorkerStatusInfo, last_activity_at: datetime | None, stamp: datetime) -> dict[str, object]:
    return {
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
        'compute_worker_scope': _required_identity_value(status.scope, 'scope'),
        'compute_worker_reuse_policy': _required_identity_value(status.reuse_policy, 'reuse_policy'),
        'datasource_id': status.datasource_id,
        'build_id': status.build_id,
        'current_job_id': status.current_job_id,
        'current_build_id': status.current_build_id,
        'current_compute_worker_run_id': status.current_engine_run_id,
        'resource_config_json': copy_json_object(status.resource_config),
        'effective_resources_json': copy_json_object(status.effective_resources),
        'last_activity_at': _read_dt(status.last_activity) or last_activity_at or stamp,
    }


def _apply_engine_status(row: ComputeWorkerInstance, *, status: ComputeWorkerStatusInfo, stamp: datetime) -> None:
    projection = _engine_status_projection(status=status, last_activity_at=row.last_activity_at, stamp=stamp)
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
    status: ComputeWorkerStatusInfo,
    now: datetime | None = None,
    commit: bool,
) -> ComputeWorkerInstance:
    if commit:
        _lock_engine_snapshot(session, worker_id=worker_id, namespace=namespace)
    stamp = now or _utcnow()
    scope = _required_identity_value(status.scope, 'scope')
    instance_id = f'{worker_id}:{namespace}:{scope}:{status.resource_id}'
    row = session.get(ComputeWorkerInstance, instance_id)
    if row is None:
        row = ComputeWorkerInstance(
            id=instance_id,
            worker_id=worker_id,
            namespace=namespace,
            analysis_id=status.analysis_id,
            compute_worker_scope=scope,
            compute_worker_reuse_policy=_required_identity_value(status.reuse_policy, 'reuse_policy'),
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
            current_compute_worker_run_id=status.current_engine_run_id,
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
        row = session.get(ComputeWorkerInstance, instance_id)
        if row is None:
            raise
        _apply_engine_status(row, status=status, stamp=stamp)
        session.add(row)
        session.commit()
    session.refresh(row)
    return row


def upsert_engine_status(
    session: Session, *, worker_id: str, namespace: str, status: ComputeWorkerStatusInfo, now: datetime | None = None
) -> ComputeWorkerInstance:
    """Persist one engine projection for callers that own a single update."""
    return _upsert_engine_status(session, worker_id=worker_id, namespace=namespace, status=status, now=now, commit=True)


def persist_compute_worker_snapshot(
    session: Session,
    *,
    worker_id: str,
    namespace: str,
    statuses: list[ComputeWorkerStatusInfo],
    now: datetime | None = None,
    phase_timings: dict[str, float] | None = None,
) -> None:
    """Persist one namespace snapshot in one transaction.

    Engine lifecycle changes can include several identities at once. Committing
    each row independently turns one projection update into a serial database
    round trip per engine and lets snapshot traffic starve lease/control RPCs.
    The coordinator is the fenced owner, so the whole namespace projection can
    be written atomically and observed as one state transition.
    """
    for attempt in range(2):
        lock_started = _snapshot_phase_clock()
        _lock_engine_snapshot(session, worker_id=worker_id, namespace=namespace)
        advisory_lock_wait_ms = (_snapshot_phase_clock() - lock_started) * 1000
        if phase_timings is not None:
            phase_timings['advisory_lock_wait_ms'] = phase_timings.get('advisory_lock_wait_ms', 0.0) + advisory_lock_wait_ms
        snapshot_started = _snapshot_phase_clock()
        try:
            _persist_engine_snapshot_locked(
                session,
                worker_id=worker_id,
                namespace=namespace,
                statuses=statuses,
                now=now,
                phase_timings=phase_timings,
            )
            snapshot_write_ms = (_snapshot_phase_clock() - snapshot_started) * 1000
            if phase_timings is not None:
                phase_timings['snapshot_write_ms'] = phase_timings.get('snapshot_write_ms', 0.0) + snapshot_write_ms
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
    statuses: list[ComputeWorkerStatusInfo],
    now: datetime | None,
    phase_timings: dict[str, float] | None,
) -> None:
    stamp = now or _utcnow()
    phase_started = _start_snapshot_phase(phase_timings)
    active_by_id: dict[str, ComputeWorkerStatusInfo] = {}
    for status in statuses:
        scope = _required_identity_value(status.scope, 'scope')
        resource_id = _required_identity_value(status.resource_id, 'resource_id')
        active_by_id[f'{worker_id}:{namespace}:{scope}:{resource_id}'] = status
    _finish_snapshot_phase(phase_timings, 'active_id_mapping_ms', phase_started)

    existing: dict[str, Any] = {}
    phase_started = _start_snapshot_phase(phase_timings)
    if active_by_id:
        columns = (
            col(ComputeWorkerInstance.id),
            *(col(getattr(ComputeWorkerInstance, field)) for field in _ENGINE_STATUS_PROJECTION_FIELDS),
        )
        result = session.execute(select(*columns).where(col(ComputeWorkerInstance.id).in_(active_by_id)))
        existing = {row['id']: row for row in result.mappings()}
    _finish_snapshot_phase(phase_timings, 'existing_row_query_fetch_ms', phase_started)

    phase_started = _start_snapshot_phase(phase_timings)
    updates: list[dict[str, object]] = []
    for instance_id, status in active_by_id.items():
        row = existing.get(instance_id)
        if row is None:
            scope = _required_identity_value(status.scope, 'scope')
            row = ComputeWorkerInstance(
                id=instance_id,
                worker_id=worker_id,
                namespace=namespace,
                analysis_id=status.analysis_id,
                compute_worker_scope=scope,
                compute_worker_reuse_policy=_required_identity_value(status.reuse_policy, 'reuse_policy'),
                last_seen_at=stamp,
                updated_at=stamp,
            )
            _apply_engine_status(row, status=status, stamp=stamp)
            session.add(row)
            continue

        projection = _engine_status_projection(status=status, last_activity_at=row['last_activity_at'], stamp=stamp)
        changed = {field: value for field, value in projection.items() if row[field] != value}
        if changed:
            updates.append({'id': instance_id, **changed, 'last_seen_at': stamp, 'updated_at': stamp})
    if updates:
        session.execute(update(ComputeWorkerInstance).execution_options(synchronize_session=False), updates)
    _finish_snapshot_phase(phase_timings, 'applying_statuses_ms', phase_started)

    phase_started = _start_snapshot_phase(phase_timings)
    prior_worker_ids = runtime_workers_service.reclaimable_worker_ids(session, kind=RuntimeWorkerKind.COORDINATOR) - {worker_id}
    worker_ids_to_stop = prior_worker_ids | {worker_id}
    stop_engines = (
        update(ComputeWorkerInstance)
        .where(col(ComputeWorkerInstance.worker_id).in_(worker_ids_to_stop))
        .where(col(ComputeWorkerInstance.namespace) == namespace)
        .where(col(ComputeWorkerInstance.status) != EngineInstanceStatus.STOPPED.value)
    )
    if active_by_id:
        stop_engines = stop_engines.where(col(ComputeWorkerInstance.id).not_in(active_by_id))
    session.execute(
        stop_engines.values(
            status=EngineInstanceStatus.STOPPED.value,
            current_job_id=None,
            current_build_id=None,
            current_compute_worker_run_id=None,
            last_seen_at=stamp,
            updated_at=stamp,
        ).execution_options(synchronize_session=False)
    )
    _finish_snapshot_phase(phase_timings, 'stale_row_sweep_ms', phase_started)

    phase_started = _start_snapshot_phase(phase_timings)
    runtime_ipc.notify_runtime_payload_on_commit(
        session,
        {'kind': RuntimePayloadKind.ENGINE.value, 'namespace': namespace},
    )
    _finish_snapshot_phase(phase_timings, 'notification_enqueue_ms', phase_started)

    phase_started = _start_snapshot_phase(phase_timings)
    session.commit()
    _finish_snapshot_phase(phase_timings, 'snapshot_commit_ms', phase_started)


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
    stmt = select(ComputeWorkerInstance).where(sa(ComputeWorkerInstance.worker_id == worker_id)).where(sa(ComputeWorkerInstance.namespace == namespace))
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
        row.current_compute_worker_run_id = None
        row.last_seen_at = stamp
        row.updated_at = stamp
        session.add(row)
        updated += 1
    if updated and commit:
        session.commit()
    return updated


def list_engine_instances(session: Session, *, namespace: str) -> list[ComputeWorkerInstance]:
    active = [status for status in EngineInstanceStatus.members() if status.is_active]
    stmt = (
        select(ComputeWorkerInstance)
        .where(sa(ComputeWorkerInstance.namespace == namespace))
        .where(col(ComputeWorkerInstance.status).in_(active))
        .order_by(
            sa(ComputeWorkerInstance.compute_worker_scope),
            sa(ComputeWorkerInstance.analysis_id),
            sa(ComputeWorkerInstance.datasource_id),
            sa(ComputeWorkerInstance.build_id),
        )
    )
    return list(session.execute(stmt).scalars().all())


def list_engine_projection(session: Session, *, namespace: str) -> list[ComputeWorkerInstance]:
    rows = list_engine_instances(session, namespace=namespace)
    latest: dict[str, ComputeWorkerInstance] = {}
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
    stmt = select(func.max(ComputeWorkerInstance.updated_at)).where(sa(ComputeWorkerInstance.namespace == namespace))
    value = session.execute(stmt).scalar_one()
    return value if isinstance(value, datetime) else None


def serialize_engine_instance(row: ComputeWorkerInstance, *, defaults: dict[str, object]) -> dict[str, object]:
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
        'scope': row.compute_worker_scope,
        'reuse_policy': row.compute_worker_reuse_policy,
        'datasource_id': row.datasource_id,
        'build_id': row.build_id,
        'current_build_id': row.current_build_id or row.build_id,
        'current_engine_run_id': row.current_compute_worker_run_id,
    }


def _row_identity_key(row: ComputeWorkerInstance) -> str:
    return f'{row.compute_worker_scope}:{_row_resource_id(row)}'


def _row_resource_id(row: ComputeWorkerInstance) -> str:
    if row.compute_worker_scope == 'datasource_preview' and row.datasource_id:
        return row.datasource_id
    if row.compute_worker_scope == 'build' and row.build_id:
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
