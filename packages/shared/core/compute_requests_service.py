import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session

from contracts.compute_requests.models import ComputeRequest, ComputeRequestKind, ComputeRequestStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_request(session: Session, *, namespace: str, kind: ComputeRequestKind | str, request_json: dict[str, object]) -> ComputeRequest:
    now = _utcnow()
    request = ComputeRequest(
        id=str(uuid.uuid4()),
        namespace=namespace,
        kind=kind if isinstance(kind, ComputeRequestKind) else ComputeRequestKind(kind),
        status=ComputeRequestStatus.QUEUED,
        request_json=request_json,
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def get_request(session: Session, request_id: str) -> ComputeRequest | None:
    return session.get(ComputeRequest, request_id)


def claim_next_request(session: Session, *, worker_id: str, reclaimable_owner_ids: set[str] | None = None) -> ComputeRequest | None:
    now = _utcnow()
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    queued_clause = table.c.status == ComputeRequestStatus.QUEUED
    reclaimable_clause = and_(table.c.status == ComputeRequestStatus.RUNNING, or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable)))
    base = select(ComputeRequest).where(or_(queued_clause, reclaimable_clause)).order_by(table.c.created_at).limit(1)
    dialect = session.get_bind().dialect.name
    stmt = base.with_for_update(skip_locked=True) if dialect == 'postgresql' else base
    row = session.execute(stmt).scalars().first()
    if row is None:
        return None
    previous_status = row.status
    previous_owner = row.lease_owner
    claim = update(ComputeRequest).where(ComputeRequest.id == row.id).where(ComputeRequest.status == previous_status)  # type: ignore[arg-type]
    claim = (
        claim.where(table.c.lease_owner.is_(None)) if previous_owner is None else claim.where(ComputeRequest.lease_owner == previous_owner)  # type: ignore[arg-type]
    )
    result = cast(
        CursorResult[Any], session.execute(claim.values(status=ComputeRequestStatus.RUNNING, lease_owner=worker_id, lease_expires_at=None, updated_at=now))
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.commit()
    claimed = session.get(ComputeRequest, row.id)
    return claimed


def mark_request_completed(
    session: Session,
    request_id: str,
    *,
    response_json: dict[str, object] | None = None,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
) -> ComputeRequest:
    request = session.get(ComputeRequest, request_id)
    if request is None:
        raise ValueError(f'Compute request {request_id} not found')
    request.status = ComputeRequestStatus.COMPLETED
    request.response_json = response_json
    request.error_message = None
    request.artifact_path = artifact_path
    request.artifact_name = artifact_name
    request.artifact_content_type = artifact_content_type
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.lease_expires_at = None
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def mark_request_failed(session: Session, request_id: str, *, error_message: str, response_json: dict[str, object] | None = None) -> ComputeRequest:
    session.rollback()
    request = session.get(ComputeRequest, request_id)
    if request is None:
        raise ValueError(f'Compute request {request_id} not found')
    request.status = ComputeRequestStatus.FAILED
    request.error_message = error_message
    request.response_json = response_json
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.lease_expires_at = None
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def queued_request_count(session: Session) -> int:
    stmt = select(ComputeRequest).where(ComputeRequest.status == ComputeRequestStatus.QUEUED)  # type: ignore[arg-type]
    return len(session.execute(stmt).scalars().all())


def release_worker_requests(session: Session, *, worker_id: str) -> list[ComputeRequest]:
    now = _utcnow()
    stmt = (
        select(ComputeRequest)
        .where(ComputeRequest.status == ComputeRequestStatus.RUNNING)  # type: ignore[arg-type]
        .where(ComputeRequest.lease_owner == worker_id)  # type: ignore[arg-type]
    )
    rows = list(session.execute(stmt).scalars().all())
    for row in rows:
        row.status = ComputeRequestStatus.QUEUED
        row.lease_owner = None
        row.lease_expires_at = None
        row.updated_at = now
        session.add(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def cleanup_completed_requests(session: Session, *, older_than_seconds: int) -> int:
    cutoff = _utcnow() - timedelta(seconds=older_than_seconds)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    stmt = select(ComputeRequest).where(table.c.completed_at.is_not(None)).where(table.c.completed_at < cutoff)
    rows = list(session.execute(stmt).scalars().all())
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)
