from datetime import datetime, timedelta

from sqlalchemy import or_, update
from sqlmodel import Session, select

from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.persistence.runtime_workers.models import RuntimeWorker
from backend_core.sqlmodel_typing import col, sa
from backend_core.time import utc_now as _utcnow

# A registration silent this long belongs to a process that died without a
# graceful stop; its leases expired long ago. A paused process that resumes
# finds its heartbeat rejected and re-registers.
_ABANDONED_AFTER = timedelta(minutes=5)


def register_worker(
    session: Session, *, worker_id: str, kind: RuntimeWorkerKind, hostname: str, pid: int, capacity: int, active_jobs: int = 0, now: datetime | None = None
) -> RuntimeWorker:
    stamp = now or _utcnow()
    worker = session.get(RuntimeWorker, worker_id)
    if worker is None:
        worker = RuntimeWorker(
            id=worker_id,
            kind=kind,
            hostname=hostname,
            pid=pid,
            capacity=capacity,
            active_jobs=active_jobs,
            started_at=stamp,
            last_heartbeat_at=stamp,
            updated_at=stamp,
        )
    else:
        worker.kind = kind
        worker.hostname = hostname
        worker.pid = pid
        worker.capacity = capacity
        worker.active_jobs = active_jobs
        worker.last_heartbeat_at = stamp
        worker.updated_at = stamp
        worker.stopped_at = None
    session.add(worker)
    session.execute(
        update(RuntimeWorker)
        .where(sa(RuntimeWorker.kind == kind))
        .where(sa(RuntimeWorker.id != worker_id))
        .where(col(RuntimeWorker.stopped_at).is_(None))
        .where(sa(RuntimeWorker.last_heartbeat_at < stamp - _ABANDONED_AFTER))
        .values(stopped_at=RuntimeWorker.last_heartbeat_at, active_jobs=0, updated_at=stamp)
    )
    session.commit()
    session.refresh(worker)
    return worker


def heartbeat_worker(session: Session, *, worker_id: str, active_jobs: int | None = None, now: datetime | None = None) -> None:
    stamp = now or _utcnow()
    values: dict[str, object] = {'last_heartbeat_at': stamp, 'updated_at': stamp}
    if active_jobs is not None:
        values['active_jobs'] = active_jobs
    result = session.execute(update(RuntimeWorker).where(sa(RuntimeWorker.id == worker_id)).where(col(RuntimeWorker.stopped_at).is_(None)).values(**values))
    if getattr(result, 'rowcount', None) != 1:
        raise ValueError(f'Runtime worker {worker_id} is not registered')
    session.commit()


def mark_worker_stopped(session: Session, *, worker_id: str, now: datetime | None = None) -> RuntimeWorker:
    worker = session.get(RuntimeWorker, worker_id)
    if worker is None:
        raise ValueError(f'Runtime worker {worker_id} not found')
    stamp = now or _utcnow()
    worker.active_jobs = 0
    worker.last_heartbeat_at = stamp
    worker.updated_at = stamp
    worker.stopped_at = stamp
    session.add(worker)
    session.commit()
    session.refresh(worker)
    return worker


def reclaimable_worker_ids(session: Session, *, kind: RuntimeWorkerKind, heartbeat_seconds: float = 15.0) -> set[str]:
    cutoff = _utcnow() - timedelta(seconds=heartbeat_seconds)
    statement = (
        select(RuntimeWorker.id)
        .where(sa(RuntimeWorker.kind == kind))
        .where(sa(or_(col(RuntimeWorker.stopped_at).is_not(None), col(RuntimeWorker.last_heartbeat_at) < cutoff)))
    )
    # Claim RPCs run this check for every durable request. Return only the
    # reclaimable IDs and let PostgreSQL apply the indexed heartbeat predicate;
    # loading and scanning the complete worker registry on every claim scales
    # with unrelated runtime workers.
    return set(session.exec(statement).all())
