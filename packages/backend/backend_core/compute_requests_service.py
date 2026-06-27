import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session

from backend_core import runtime_outbox_service
from backend_core.config import settings
from backend_core.domain.compute_requests.models import (
    command_envelope,
    command_envelope_from_json,
    command_payload as proto_command_payload,
    compute_request_kind_name,
    compute_request_status_name,
    envelope_to_json,
    kind_from_proto,
    response_envelope,
    response_envelope_from_json,
    response_payload as proto_response_payload,
    status_from_proto,
)
from backend_core.persistence.compute_requests.models import ComputeRequest
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


def _request_priority_clause(table):
    return case(
        *[(table.c.kind == kind, 0) for kind in _BLOCKING_REQUEST_KINDS],
        *[(table.c.kind == kind, 1) for kind in _INTERACTIVE_REQUEST_KINDS],
        else_=2,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def create_request(
    session: Session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    command: compute_pb2.ComputeCommand,
    commit: bool = True,
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
        request_json=envelope_to_json(envelope),
        created_at=now,
        updated_at=now,
    )
    session.add(request)
    if commit:
        session.commit()
        session.refresh(request)
    else:
        session.flush()
    return request


def command_payload(request: ComputeRequest) -> dict[str, object]:
    envelope = command_envelope_from_json(request.request_json)
    row_kind = kind_from_proto(request.kind)
    if kind_from_proto(envelope.kind) != row_kind:
        raise ValueError(
            f'Compute request {request.id} envelope kind {compute_request_kind_name(kind_from_proto(envelope.kind))!r} '
            f'does not match row kind {compute_request_kind_name(row_kind)!r}'
        )
    if envelope.correlation_id != request.id:
        raise ValueError(f'Compute request {request.id} envelope correlation id {envelope.correlation_id!r} does not match request id')
    return proto_command_payload(envelope)


def command_envelope_for_request(request: ComputeRequest):
    envelope = command_envelope_from_json(request.request_json)
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
    if request.response_json is None:
        raise ValueError(f'Compute request {request.id} has no response envelope')
    envelope = response_envelope_from_json(request.response_json)
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


def claim_next_request(session: Session, *, worker_id: str, reclaimable_owner_ids: set[str] | None = None) -> ComputeRequest | None:
    now = _utcnow()
    table = ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
    reclaimable = set(reclaimable_owner_ids or ())
    queued_clause = table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
    reclaimable_clause = and_(
        table.c.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
        or_(table.c.lease_owner.is_(None), table.c.lease_owner.in_(reclaimable), table.c.lease_expires_at <= now),
    )
    base = select(ComputeRequest).where(or_(queued_clause, reclaimable_clause)).order_by(_request_priority_clause(table), table.c.created_at).limit(1)
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
        CursorResult[Any],
        session.execute(
            claim.values(
                status=enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=settings.runtime_work_lease_ttl_seconds),
                updated_at=now,
            )
        ),
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
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    request.response_json = envelope_to_json(
        response_envelope(
            kind=kind_from_proto(request.kind),
            status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
            payload=response_json or {},
            request_id=request.id,
        )
    )
    request.error_message = None
    request.artifact_path = artifact_path
    request.artifact_name = artifact_name
    request.artifact_content_type = artifact_content_type
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.lease_expires_at = None
    session.add(request)
    runtime_outbox_service.enqueue_compute_response_notification(session, request_id=request.id, commit=False)
    session.commit()
    session.refresh(request)
    return request


def mark_request_failed(session: Session, request_id: str, *, error_message: str, response_json: dict[str, object] | None = None) -> ComputeRequest:
    session.rollback()
    request = session.get(ComputeRequest, request_id)
    if request is None:
        raise ValueError(f'Compute request {request_id} not found')
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    request.error_message = error_message
    request.response_json = envelope_to_json(
        response_envelope(
            kind=kind_from_proto(request.kind),
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            payload=response_json or {},
            request_id=request.id,
            error_message=error_message,
        )
    )
    request.completed_at = _utcnow()
    request.updated_at = request.completed_at
    request.lease_owner = None
    request.lease_expires_at = None
    session.add(request)
    runtime_outbox_service.enqueue_compute_response_notification(session, request_id=request.id, commit=False)
    session.commit()
    session.refresh(request)
    return request


def queued_request_count(session: Session) -> int:
    stmt = select(ComputeRequest).where(ComputeRequest.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED)  # type: ignore[arg-type]
    return len(session.execute(stmt).scalars().all())


def release_worker_requests(session: Session, *, worker_id: str) -> list[ComputeRequest]:
    now = _utcnow()
    stmt = (
        select(ComputeRequest)
        .where(ComputeRequest.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING)  # type: ignore[arg-type]
        .where(ComputeRequest.lease_owner == worker_id)  # type: ignore[arg-type]
    )
    rows = list(session.execute(stmt).scalars().all())
    for row in rows:
        row.status = enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
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
