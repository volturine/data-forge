from datetime import UTC, datetime

from sqlmodel import Session, select

from contracts.runtime_workers.models import RuntimeWorker, RuntimeWorkerKind


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    session.commit()
    session.refresh(worker)
    return worker


def heartbeat_worker(session: Session, *, worker_id: str, active_jobs: int | None = None, now: datetime | None = None) -> RuntimeWorker:
    worker = session.get(RuntimeWorker, worker_id)
    if worker is None:
        raise ValueError(f'Runtime worker {worker_id} not found')
    stamp = now or _utcnow()
    if active_jobs is not None:
        worker.active_jobs = active_jobs
    worker.last_heartbeat_at = stamp
    worker.updated_at = stamp
    session.add(worker)
    session.commit()
    session.refresh(worker)
    return worker


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


def get_worker(session: Session, worker_id: str) -> RuntimeWorker | None:
    return session.get(RuntimeWorker, worker_id)


def list_workers(session: Session, *, kind: RuntimeWorkerKind | None = None) -> list[RuntimeWorker]:
    stmt = select(RuntimeWorker)
    if kind is not None:
        stmt = stmt.where(RuntimeWorker.kind == kind)  # type: ignore[arg-type]
    stmt = stmt.order_by(RuntimeWorker.started_at)  # type: ignore[arg-type]
    return list(session.execute(stmt).scalars().all())


def worker_available(session: Session, *, kind: RuntimeWorkerKind, heartbeat_seconds: float = 15.0) -> bool:
    now = _utcnow()
    for worker in reversed(list_workers(session, kind=kind)):
        if worker.is_reclaimable(now=now, heartbeat_seconds=heartbeat_seconds):
            continue
        return True
    return False


def reclaimable_worker_ids(session: Session, *, kind: RuntimeWorkerKind, heartbeat_seconds: float = 15.0) -> set[str]:
    now = _utcnow()
    return {worker.id for worker in list_workers(session, kind=kind) if worker.is_reclaimable(now=now, heartbeat_seconds=heartbeat_seconds)}
