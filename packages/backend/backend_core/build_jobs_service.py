import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session

from backend_core import runtime_work_service
from backend_core.claiming import CLAIM_DELIVERY_LEASE_SECONDS, claim_by_lease_owner, database_lease_clock, with_for_update_skip_locked
from backend_core.config import settings
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.lease_observability import record_lease_transition
from backend_core.namespace import get_namespace
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.runtime_work_service import RuntimeWorkKind
from backend_core.sqlmodel_typing import sa
from backend_core.transactions import committed
from backend_core.transitions import TransitionOutcome, TransitionResult, applied, rejected

_RECONCILIATION_BATCH_SIZE = 100
_BUILD_WORK_PENDING_QUERY = """
    SELECT 1
    FROM build_jobs
    WHERE status = 'queued'
       OR (
            status IN ('leased', 'running')
            AND (lease_owner IS NULL OR lease_expires_at <= statement_timestamp())
       )
"""
_BUILD_WORK_DUE_QUERY = """
    SELECT min(lease_expires_at)
    FROM build_jobs
    WHERE status IN ('leased', 'running')
      AND lease_expires_at > statement_timestamp()
"""


def _database_now(session: Session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise TypeError('Database CURRENT_TIMESTAMP did not return a datetime')
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def stage_job(
    session: Session,
    *,
    build_id: str,
    namespace: str,
    status: BuildJobStatus | str = BuildJobStatus.QUEUED,
    priority: int = 0,
    max_attempts: int = 1,
    available_at: datetime | None = None,
) -> BuildJob:
    # Claims compare availability against PostgreSQL CURRENT_TIMESTAMP. Use the
    # same clock when staging so a host/database clock skew cannot hide a fresh
    # job from the very next worker claim.
    now = _database_now(session)
    job = BuildJob(
        id=str(uuid.uuid4()),
        build_id=build_id,
        namespace=namespace,
        status=status if isinstance(status, BuildJobStatus) else BuildJobStatus.require(status),
        priority=priority,
        attempts=0,
        max_attempts=max_attempts,
        available_at=available_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()
    runtime_work_service.append_wake(session, namespace=namespace, kind=RuntimeWorkKind.BUILD)
    return job


create_job = committed(stage_job, refresh=True)


def get_job_by_build_id(session: Session, build_id: str) -> BuildJob | None:
    stmt = select(BuildJob).where(sa(BuildJob.build_id == build_id))
    return session.execute(stmt).scalars().first()


def claim_next_job(session: Session, *, worker_id: str, reclaimable_owner_ids: set[str] | None = None) -> BuildJob | None:
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    queued_clause = table.c.status == BuildJobStatus.QUEUED
    reclaimable_statuses = [status for status in BuildJobStatus.members() if status.is_reclaimable]
    lease_expired_clause = table.c.lease_expires_at <= now
    reclaimable_clause = and_(
        table.c.status.in_(reclaimable_statuses),
        or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable), lease_expired_clause),
        table.c.attempts < table.c.max_attempts,
    )
    base = (
        select(BuildJob)
        .where(sa(BuildJob.available_at <= now))
        .where(or_(queued_clause, reclaimable_clause))
        .order_by(desc(sa(BuildJob.priority)), sa(BuildJob.available_at), sa(BuildJob.created_at), sa(BuildJob.id))
        .limit(1)
    )
    stmt = with_for_update_skip_locked(session, base)
    row = session.execute(stmt).scalars().first()
    if row is None:
        session.rollback()
        return None
    current_attempts = row.attempts
    current_generation = row.lease_generation
    previous_status = row.status
    previous_owner = row.lease_owner
    claim_token = str(uuid.uuid4())
    lease_now = database_lease_clock(session, now)
    claimed = claim_by_lease_owner(
        session,
        BuildJob,
        table=table,
        row_id=row.id,
        previous_owner=previous_owner,
        extra_conditions=(
            table.c.attempts == current_attempts,
            table.c.lease_generation == current_generation,
            table.c.status == previous_status,
        ),
        values={
            'status': BuildJobStatus.RUNNING,
            'lease_owner': worker_id,
            'claim_token': claim_token,
            'lease_generation': current_generation + 1,
            'lease_expires_at': lease_now + timedelta(seconds=CLAIM_DELIVERY_LEASE_SECONDS),
            'claimed_at': lease_now,
            'last_renewed_at': lease_now,
            'attempts': current_attempts + 1,
            'updated_at': lease_now,
        },
    )
    if not claimed:
        session.rollback()
        return None
    session.commit()
    job = session.get(BuildJob, row.id)
    if job is None:
        session.rollback()
        return None
    record_lease_transition(
        kind='build_job',
        transition='reclaim' if previous_owner is not None else 'claim',
        outcome=TransitionOutcome.APPLIED,
        entity_id=job.id,
        owner_id=worker_id,
        claim_token=claim_token,
        generation=job.lease_generation,
        attempt=job.attempts,
    )
    return job


def stage_exhausted_jobs(session: Session) -> list[str]:
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    base = (
        select(BuildJob)
        .where(table.c.status.in_([status for status in BuildJobStatus.members() if status.is_reclaimable]))
        .where(table.c.lease_expires_at <= now)
        .where(table.c.attempts >= table.c.max_attempts)
        .order_by(sa(BuildJob.lease_expires_at), sa(BuildJob.id))
        # Reconciliation is a recovery pass, not a reason for one count RPC
        # to load every historical exhausted job in the namespace.
        .limit(_RECONCILIATION_BATCH_SIZE)
    )
    rows = list(session.execute(with_for_update_skip_locked(session, base)).scalars().all())
    if not rows:
        runtime_work_service.refresh_pending_work(
            session,
            namespace=get_namespace(),
            kind=RuntimeWorkKind.BUILD,
            pending_query=_BUILD_WORK_PENDING_QUERY,
            due_query=_BUILD_WORK_DUE_QUERY,
        )
        return []
    build_ids: list[str] = []
    for row in rows:
        owner_id = row.lease_owner or 'unowned'
        claim_token = row.claim_token or ''
        generation = row.lease_generation
        attempt = row.attempts
        build_ids.append(row.build_id)
        row.status = BuildJobStatus.FAILED
        row.last_error = 'Build job lease expired after maximum attempts'
        row.clear_lease()
        row.updated_at = now
        session.add(row)
        session.execute(
            update(BuildRun)
            .where(BuildRun.metadata.tables[BuildRun.__tablename__].c.id == row.build_id)
            .where(BuildRun.metadata.tables[BuildRun.__tablename__].c.status.in_([BuildRunStatus.QUEUED, BuildRunStatus.RUNNING]))
            .values(
                status=BuildRunStatus.ORPHANED,
                error_message='Build job lease expired after maximum attempts',
                completed_at=now,
                updated_at=now,
            )
        )
        record_lease_transition(
            kind='build_job',
            transition='exhaust',
            outcome=TransitionOutcome.APPLIED,
            entity_id=row.id,
            owner_id=owner_id,
            claim_token=claim_token,
            generation=generation,
            attempt=attempt,
        )
    session.flush()
    runtime_work_service.refresh_pending_work(
        session,
        namespace=get_namespace(),
        kind=RuntimeWorkKind.BUILD,
        pending_query=_BUILD_WORK_PENDING_QUERY,
        due_query=_BUILD_WORK_DUE_QUERY,
    )
    return build_ids


expire_exhausted_jobs = committed(stage_exhausted_jobs)


def renew_job_lease(session: Session, job_id: str, *, worker_id: str, claim_token: str, lease_generation: int) -> TransitionResult[BuildJob]:
    now = _database_now(session)
    lease_now = database_lease_clock(session, now)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    statement = (
        update(BuildJob)
        .where(table.c.id == job_id)
        .where(table.c.status == BuildJobStatus.RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > lease_now)
        .values(
            lease_expires_at=lease_now + timedelta(seconds=settings.runtime_work_lease_ttl_seconds),
            last_renewed_at=lease_now,
            updated_at=lease_now,
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    if result.rowcount != 1:
        session.rollback()
        outcome = TransitionOutcome.NOT_FOUND if session.get(BuildJob, job_id) is None else TransitionOutcome.LEASE_LOST
        record_lease_transition(
            kind='build_job',
            transition='renew',
            outcome=outcome,
            entity_id=job_id,
            owner_id=worker_id,
            claim_token=claim_token,
            generation=lease_generation,
        )
        return rejected(outcome)
    session.commit()
    job = session.get(BuildJob, job_id)
    if job is None:
        raise RuntimeError(f'Renewed build job {job_id} disappeared after commit')
    record_lease_transition(
        kind='build_job',
        transition='renew',
        outcome=TransitionOutcome.APPLIED,
        entity_id=job_id,
        owner_id=worker_id,
        claim_token=claim_token,
        generation=lease_generation,
        attempt=job.attempts,
    )
    return applied(job)


def _active_job_claim(
    session: Session,
    job_id: str,
    *,
    build_id: str,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    lock: bool,
) -> BuildJob | None:
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    statement = (
        select(BuildJob)
        .where(table.c.id == job_id)
        .where(table.c.build_id == build_id)
        .where(table.c.status == BuildJobStatus.RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > now)
    )
    if lock:
        statement = statement.with_for_update()
    return session.execute(statement).scalars().first()


def lock_active_job_claim(
    session: Session,
    job_id: str,
    *,
    build_id: str,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> BuildJob | None:
    return _active_job_claim(
        session,
        job_id,
        build_id=build_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        lock=True,
    )


def get_active_job_claim(
    session: Session,
    job_id: str,
    *,
    build_id: str,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> BuildJob | None:
    """Validate a progress event without locking out concurrent lease renewals.

    The event transaction is separately fenced by BuildRun.execution_generation;
    terminal job transitions still use the locking claim validator.
    """
    return _active_job_claim(
        session,
        job_id,
        build_id=build_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        lock=False,
    )


def finish_claimed_job(
    session: Session,
    job_id: str,
    *,
    worker_id: str,
    build_id: str,
    claim_token: str,
    lease_generation: int,
    status: BuildJobStatus,
    error: str | None = None,
) -> BuildJob | None:
    if status not in {BuildJobStatus.COMPLETED, BuildJobStatus.FAILED, BuildJobStatus.CANCELLED}:
        raise ValueError(f'Unsupported claimed build job terminal status: {status.value}')
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    statement = (
        update(BuildJob)
        .where(table.c.id == job_id)
        .where(table.c.build_id == build_id)
        .where(table.c.status == BuildJobStatus.RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > now)
        .values(
            status=status,
            lease_owner=None,
            claim_token=None,
            lease_expires_at=None,
            claimed_at=None,
            last_renewed_at=None,
            last_error=error,
            updated_at=now,
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    if result.rowcount != 1:
        return None
    session.flush()
    return session.get(BuildJob, job_id)


def stage_job_cancelled(session: Session, job_id: str) -> BuildJob:
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    cancellable_statuses = [BuildJobStatus.QUEUED, *[status for status in BuildJobStatus.members() if status.is_active]]
    statement = (
        update(BuildJob)
        .where(table.c.id == job_id)
        .where(table.c.status.in_(cancellable_statuses))
        .values(
            status=BuildJobStatus.CANCELLED,
            lease_owner=None,
            claim_token=None,
            lease_generation=table.c.lease_generation + 1,
            lease_expires_at=None,
            claimed_at=None,
            last_renewed_at=None,
            updated_at=now,
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    if result.rowcount == 1:
        session.flush()
        job = session.get(BuildJob, job_id)
        if job is None:
            raise RuntimeError(f'Cancelled build job {job_id} disappeared')
        return job
    session.expire_all()
    job = session.get(BuildJob, job_id)
    if job is None:
        raise ValueError(f'Build job {job_id} not found')
    return job


mark_job_cancelled = committed(stage_job_cancelled, refresh=True)


def queued_job_count(session: Session) -> int:
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    stmt = (
        select(func.count())
        .select_from(table)
        .where(
            or_(
                table.c.status == BuildJobStatus.QUEUED,
                and_(
                    table.c.status.in_([status for status in BuildJobStatus.members() if status.is_reclaimable]),
                    table.c.lease_expires_at <= now,
                    table.c.attempts < table.c.max_attempts,
                ),
            )
        )
    )
    return session.execute(stmt).scalar_one()


def release_worker_jobs(session: Session, *, worker_id: str) -> list[BuildJob]:
    now = _database_now(session)
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    stmt = (
        select(BuildJob)
        .where(sa(BuildJob.lease_owner == worker_id))
        .where(table.c.status.in_([status for status in BuildJobStatus.members() if status.is_reclaimable]))
    )
    jobs = list(session.execute(with_for_update_skip_locked(session, stmt)).scalars().all())
    for job in jobs:
        job.status = BuildJobStatus.QUEUED
        job.clear_lease()
        job.updated_at = now
        session.add(job)
    session.commit()
    for job in jobs:
        session.refresh(job)
    return jobs
