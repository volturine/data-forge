import uuid
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session

from backend_core import runtime_outbox_service
from backend_core.claiming import claim_by_lease_owner, with_for_update_skip_locked
from backend_core.config import settings
from backend_core.domain.compute_requests.models import (
    command_envelope,
    compute_request_kind_name,
    compute_request_status_name,
    kind_from_proto,
    response_envelope,
    response_payload as proto_response_payload,
    status_from_proto,
)
from backend_core.lease_observability import record_lease_transition
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.sqlmodel_typing import sa
from backend_core.time import utc_now as _utcnow
from backend_core.transactions import committed
from backend_core.transitions import TransitionOutcome, TransitionResult, applied, rejected
from dataforge_protocol import compute_pb2, enums_pb2

_BLOCKING_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        enums_pb2.COMPUTE_REQUEST_KIND_DOWNLOAD,
        enums_pb2.COMPUTE_REQUEST_KIND_EXPORT,
    }
)

_INTERACTIVE_REQUEST_KINDS = frozenset(
    {
        enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
        enums_pb2.COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS,
    }
)


def _database_now(session: Session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise TypeError('Database CURRENT_TIMESTAMP did not return a datetime')
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _request_priority_clause(table):
    return case(
        *[(table.c.kind == kind, 0) for kind in _BLOCKING_REQUEST_KINDS],
        *[(table.c.kind == kind, 1) for kind in _INTERACTIVE_REQUEST_KINDS],
        else_=2,
    )


def stage_request(
    session: Session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
) -> ComputeRequest:
    now = _utcnow()
    request_id = str(uuid.uuid4())
    envelope = command_envelope(
        kind=kind,
        command=command,
        request_id=request_id,
    )
    request = ComputeRequest(
        id=request_id,
        namespace=namespace,
        kind=kind,
        status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        command_envelope=envelope.SerializeToString(),
        max_attempts=settings.runtime_compute_max_attempts,
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    session.flush()
    return request


create_request = committed(stage_request, refresh=True)


def command_envelope_for_request(request: ComputeRequest):
    envelope = compute_pb2.ComputeCommandEnvelope.FromString(request.command_envelope)
    row_kind = kind_from_proto(request.kind)
    if kind_from_proto(envelope.kind) != row_kind:
        raise ValueError(
            f'Compute request {request.id} envelope kind {compute_request_kind_name(kind_from_proto(envelope.kind))!r} '
            f'does not match row kind {compute_request_kind_name(row_kind)!r}'
        )
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} envelope correlation id {envelope.correlation_id!r} does not match request id')
    return envelope


def response_payload(request: ComputeRequest) -> dict[str, object]:
    if request.response_envelope is None:
        raise ValueError(f'Compute request {request.id} has no response envelope')
    envelope = compute_pb2.ComputeResponseEnvelope.FromString(request.response_envelope)
    row_kind = kind_from_proto(request.kind)
    if kind_from_proto(envelope.kind) != row_kind:
        raise ValueError(
            f'Compute request {request.id} response kind {compute_request_kind_name(kind_from_proto(envelope.kind))!r} '
            f'does not match row kind {compute_request_kind_name(row_kind)!r}'
        )
    row_status = status_from_proto(request.status)
    if status_from_proto(envelope.status) != row_status:
        raise ValueError(
            f'Compute request {request.id} response status {compute_request_status_name(status_from_proto(envelope.status))!r} '
            f'does not match row status {compute_request_status_name(row_status)!r}'
        )
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} response correlation id {envelope.correlation_id!r} does not match request id')
    return proto_response_payload(envelope)


def get_request(session: Session, request_id: str) -> ComputeRequest | None:
    return session.get(ComputeRequest, request_id)


def claim_next_request(
    session: Session,
    *,
    worker_id: str,
    reclaimable_owner_ids: set[str] | None = None,
    allowed_kinds: Collection[enums_pb2.ComputeRequestKind] | None = None,
) -> ComputeRequest | None:
    now = _database_now(session)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    exhausted_statement = with_for_update_skip_locked(
        session,
        select(ComputeRequest)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.attempts >= table.c.max_attempts)
        .where(or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable), table.c.lease_expires_at <= now))
        .order_by(table.c.created_at, table.c.id),
    )
    exhausted = list(session.execute(exhausted_statement).scalars().all())
    for request in exhausted:
        owner_id = request.lease_owner or 'unowned'
        claim_token = request.claim_token or ''
        generation = request.lease_generation
        attempt = request.attempts
        error_message = f'Compute request exhausted {request.max_attempts} execution attempts'
        request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
        request.response_envelope = response_envelope(
            kind=kind_from_proto(request.kind),
            request_id=request.id,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            payload=None,
            error_message=error_message,
        ).SerializeToString()
        request.error_message = error_message
        request.completed_at = now
        request.updated_at = now
        request.lease_owner = None
        request.claim_token = None
        request.lease_expires_at = None
        request.claimed_at = None
        request.last_renewed_at = None
        session.add(request)
        runtime_outbox_service.enqueue_compute_response_notification(session, request_id=request.id)
        record_lease_transition(
            kind='compute_request',
            transition='exhaust',
            outcome=TransitionOutcome.APPLIED,
            entity_id=request.id,
            owner_id=owner_id,
            claim_token=claim_token,
            generation=generation,
            attempt=attempt,
        )
    if exhausted:
        session.commit()
    queued_clause = table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
    reclaimable_clause = and_(
        table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
        or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable), table.c.lease_expires_at <= now),
    )
    base = select(ComputeRequest).where(or_(queued_clause, reclaimable_clause))
    if allowed_kinds is not None:
        base = base.where(table.c.kind.in_(allowed_kinds))
    base = base.order_by(_request_priority_clause(table), table.c.created_at, table.c.id).limit(1)
    stmt = with_for_update_skip_locked(session, base)
    row = session.execute(stmt).scalars().first()
    if row is None:
        return None
    previous_status = row.status
    previous_owner = row.lease_owner
    previous_generation = row.lease_generation
    claim_token = str(uuid.uuid4())
    lease_claimed = claim_by_lease_owner(
        session,
        ComputeRequest,
        table=table,
        row_id=row.id,
        previous_owner=previous_owner,
        extra_conditions=(table.c.status == previous_status, table.c.lease_generation == previous_generation),
        values={
            'status': enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
            'lease_owner': worker_id,
            'claim_token': claim_token,
            'lease_generation': previous_generation + 1,
            'lease_expires_at': now + timedelta(seconds=settings.runtime_work_lease_ttl_seconds),
            'claimed_at': now,
            'last_renewed_at': now,
            'attempts': row.attempts + 1,
            'updated_at': now,
        },
    )
    if not lease_claimed:
        session.rollback()
        return None
    session.commit()
    claimed = session.get(ComputeRequest, row.id)
    if claimed is not None:
        record_lease_transition(
            kind='compute_request',
            transition='reclaim' if previous_owner is not None else 'claim',
            outcome=TransitionOutcome.APPLIED,
            entity_id=claimed.id,
            owner_id=worker_id,
            claim_token=claim_token,
            generation=claimed.lease_generation,
            attempt=claimed.attempts,
        )
    return claimed


def renew_request_lease(
    session: Session,
    request_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> TransitionResult[ComputeRequest]:
    now = _database_now(session)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    statement = (
        update(ComputeRequest)
        .where(table.c.id == request_id)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > now)
        .values(
            lease_expires_at=now + timedelta(seconds=settings.runtime_work_lease_ttl_seconds),
            last_renewed_at=now,
            updated_at=now,
        )
    )
    result = cast(CursorResult[Any], session.execute(statement))
    if result.rowcount != 1:
        session.rollback()
        outcome = TransitionOutcome.NOT_FOUND if session.get(ComputeRequest, request_id) is None else TransitionOutcome.LEASE_LOST
        record_lease_transition(
            kind='compute_request',
            transition='renew',
            outcome=outcome,
            entity_id=request_id,
            owner_id=worker_id,
            claim_token=claim_token,
            generation=lease_generation,
        )
        return rejected(outcome)
    session.commit()
    request = session.get(ComputeRequest, request_id)
    if request is None:
        raise RuntimeError(f'Renewed compute request {request_id} disappeared after commit')
    record_lease_transition(
        kind='compute_request',
        transition='renew',
        outcome=TransitionOutcome.APPLIED,
        entity_id=request_id,
        owner_id=worker_id,
        claim_token=claim_token,
        generation=lease_generation,
        attempt=request.attempts,
    )
    return applied(request)


def lock_active_request_claim(
    session: Session,
    request_id: str,
    *,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> ComputeRequest | None:
    now = _database_now(session)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    statement = (
        select(ComputeRequest)
        .where(table.c.id == request_id)
        .where(table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)
        .where(table.c.lease_owner == worker_id)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .where(table.c.lease_expires_at > now)
        .with_for_update()
    )
    return session.execute(statement).scalars().first()


def mark_request_completed(
    session: Session,
    request_id: str,
    *,
    response_envelope: compute_pb2.ComputeResponseEnvelope,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
    artifact_path: str | None = None,
    artifact_name: str | None = None,
    artifact_content_type: str | None = None,
) -> ComputeRequest | None:
    request = lock_active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
    )
    if request is None:
        session.rollback()
        return None
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    _validate_response_envelope(request, response_envelope, enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED)
    request.response_envelope = response_envelope.SerializeToString()
    request.error_message = None
    request.artifact_path = artifact_path
    request.artifact_name = artifact_name
    request.artifact_content_type = artifact_content_type
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.claim_token = None
    request.lease_expires_at = None
    request.claimed_at = None
    request.last_renewed_at = None
    session.add(request)
    runtime_outbox_service.enqueue_compute_response_notification(session, request_id=request.id)
    session.commit()
    session.refresh(request)
    return request


def mark_request_failed(
    session: Session,
    request_id: str,
    *,
    error_message: str,
    response_envelope: compute_pb2.ComputeResponseEnvelope,
    worker_id: str,
    claim_token: str,
    lease_generation: int,
) -> ComputeRequest | None:
    request = lock_active_request_claim(
        session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
    )
    if request is None:
        session.rollback()
        return None
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    request.error_message = error_message
    _validate_response_envelope(request, response_envelope, enums_pb2.COMPUTE_REQUEST_STATUS_FAILED)
    request.response_envelope = response_envelope.SerializeToString()
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.claim_token = None
    request.lease_expires_at = None
    request.claimed_at = None
    request.last_renewed_at = None
    session.add(request)
    runtime_outbox_service.enqueue_compute_response_notification(session, request_id=request.id)
    session.commit()
    session.refresh(request)
    return request


def _validate_response_envelope(
    request: ComputeRequest,
    envelope: compute_pb2.ComputeResponseEnvelope,
    expected_status: enums_pb2.ComputeRequestStatus,
) -> None:
    if kind_from_proto(envelope.kind) != kind_from_proto(request.kind):
        raise ValueError(f'Compute request {request.id} response kind does not match request kind')
    if status_from_proto(envelope.status) != expected_status:
        raise ValueError(f'Compute request {request.id} response status does not match completion status')
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} response correlation id does not match request id')


def queued_request_count(session: Session) -> int:
    stmt = select(ComputeRequest).where(sa(ComputeRequest.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED))
    return len(session.execute(stmt).scalars().all())


def cleanup_completed_requests(session: Session, *, older_than_seconds: int) -> int:
    cutoff = _utcnow() - timedelta(seconds=older_than_seconds)
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    stmt = select(ComputeRequest).where(table.c.completed_at.is_not(None)).where(table.c.completed_at < cutoff)
    rows = list(session.execute(stmt).scalars().all())
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)
