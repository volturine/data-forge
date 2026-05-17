import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session

from contracts.build_jobs.models import BuildJob, BuildJobStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_job(
    session: Session,
    *,
    build_id: str,
    namespace: str,
    status: BuildJobStatus | str = BuildJobStatus.QUEUED,
    priority: int = 0,
    max_attempts: int = 1,
    available_at: datetime | None = None,
) -> BuildJob:
    now = _utcnow()
    job = BuildJob(
        id=str(uuid.uuid4()),
        build_id=build_id,
        namespace=namespace,
        status=status if isinstance(status, BuildJobStatus) else BuildJobStatus(status),
        priority=priority,
        attempts=0,
        max_attempts=max_attempts,
        available_at=available_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job_by_build_id(session: Session, build_id: str) -> BuildJob | None:
    stmt = select(BuildJob).where(BuildJob.build_id == build_id)  # type: ignore[arg-type]
    return session.execute(stmt).scalars().first()


def claim_next_job(session: Session, *, worker_id: str, reclaimable_owner_ids: set[str] | None = None) -> BuildJob | None:
    now = _utcnow()
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    queued_clause = table.c.status == BuildJobStatus.QUEUED
    reclaimable_statuses = [status for status in BuildJobStatus if status.is_reclaimable]
    reclaimable_clause = and_(
        table.c.status.in_(reclaimable_statuses),
        or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable)),
        table.c.attempts < table.c.max_attempts,
    )
    base = (
        select(BuildJob)
        .where(BuildJob.available_at <= now)  # type: ignore[arg-type]
        .where(or_(queued_clause, reclaimable_clause))
        .order_by(desc(BuildJob.priority), BuildJob.created_at)  # type: ignore[arg-type]
        .limit(1)
    )
    dialect = session.get_bind().dialect.name
    stmt = base.with_for_update(skip_locked=True) if dialect == 'postgresql' else base
    row = session.execute(stmt).scalars().first()
    if row is None:
        return None
    current_attempts = row.attempts
    previous_status = row.status
    previous_owner = row.lease_owner
    claim = (
        update(BuildJob)
        .where(BuildJob.id == row.id)
        .where(BuildJob.attempts == current_attempts)  # type: ignore[arg-type]
        .where(BuildJob.status == previous_status)  # type: ignore[arg-type]
    )
    claim = (
        claim.where(table.c.lease_owner.is_(None)) if previous_owner is None else claim.where(BuildJob.lease_owner == previous_owner)  # type: ignore[arg-type]
    )
    result = cast(
        CursorResult[Any],
        session.execute(
            claim.values(status=BuildJobStatus.RUNNING, lease_owner=worker_id, lease_expires_at=None, attempts=current_attempts + 1, updated_at=now)
        ),
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.commit()
    job = session.get(BuildJob, row.id)
    if job is None:
        return None
    return job


def mark_job_running(session: Session, job_id: str) -> BuildJob:
    job = session.get(BuildJob, job_id)
    if job is None:
        raise ValueError(f'Build job {job_id} not found')
    job.status = BuildJobStatus.RUNNING
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_job_completed(session: Session, job_id: str) -> BuildJob:
    job = session.get(BuildJob, job_id)
    if job is None:
        raise ValueError(f'Build job {job_id} not found')
    job.status = BuildJobStatus.COMPLETED
    job.clear_lease()
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_job_failed(session: Session, job_id: str, *, error: str | None = None) -> BuildJob:
    job = session.get(BuildJob, job_id)
    if job is None:
        raise ValueError(f'Build job {job_id} not found')
    job.status = BuildJobStatus.FAILED
    job.last_error = error
    job.clear_lease()
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_job_cancelled(session: Session, job_id: str) -> BuildJob:
    job = session.get(BuildJob, job_id)
    if job is None:
        raise ValueError(f'Build job {job_id} not found')
    job.status = BuildJobStatus.CANCELLED
    job.clear_lease()
    job.updated_at = _utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def queued_job_count(session: Session) -> int:
    stmt = select(BuildJob).where(BuildJob.status == BuildJobStatus.QUEUED)  # type: ignore[arg-type]
    return len(session.execute(stmt).scalars().all())


def release_worker_jobs(session: Session, *, worker_id: str) -> list[BuildJob]:
    now = _utcnow()
    table = BuildJob.metadata.tables[BuildJob.__tablename__]
    stmt = (
        select(BuildJob)
        .where(BuildJob.lease_owner == worker_id)  # type: ignore[arg-type]
        .where(table.c.status.in_([status for status in BuildJobStatus if status.is_reclaimable]))
    )
    jobs = list(session.execute(stmt).scalars().all())
    for job in jobs:
        job.status = BuildJobStatus.QUEUED
        job.clear_lease()
        job.updated_at = now
        session.add(job)
    session.commit()
    for job in jobs:
        session.refresh(job)
    return jobs
