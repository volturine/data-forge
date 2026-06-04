import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlmodel import Session

from backend_contracts.runtime.events import RuntimePayloadKind
from backend_core import runtime_ipc
from backend_core.config import settings
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


def enqueue_runtime_event(session: Session, payload: dict[str, object], *, commit: bool = True) -> RuntimeOutboxEvent:
    kind = RuntimePayloadKind.from_payload(payload)
    if kind is None:
        raise ValueError(f'Unsupported runtime outbox payload kind: {payload.get("kind")!r}')
    now = _utcnow()
    event = RuntimeOutboxEvent(
        id=str(uuid.uuid4()),
        kind=kind.value,
        status=RuntimeOutboxStatus.PENDING,
        payload_json=dict(payload),
        attempts=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    if commit:
        session.commit()
        session.refresh(event)
    else:
        session.flush()
    return event


def enqueue_api_build_notification(session: Session, *, namespace: str, build_id: str, latest_sequence: int, commit: bool = True) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {
            'kind': RuntimePayloadKind.BUILD.value,
            'namespace': namespace,
            'build_id': build_id,
            'latest_sequence': latest_sequence,
        },
        commit=commit,
    )


def enqueue_build_job_notification(session: Session, *, commit: bool = True) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(session, {'kind': RuntimePayloadKind.JOB.value}, commit=commit)


def enqueue_compute_request_notification(session: Session, *, request_id: str, commit: bool = True) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {'kind': RuntimePayloadKind.COMPUTE_REQUEST.value, 'request_id': request_id},
        commit=commit,
    )


def enqueue_compute_response_notification(session: Session, *, request_id: str, commit: bool = True) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request_id},
        commit=commit,
    )


def dispatch_pending_events(session: Session, *, limit: int = 100) -> int:
    now = _utcnow()
    table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    base = (
        select(RuntimeOutboxEvent)
        .where(table.c.status.in_([RuntimeOutboxStatus.PENDING, RuntimeOutboxStatus.FAILED]))
        .where(RuntimeOutboxEvent.available_at <= now)  # type: ignore[arg-type]
        .order_by(RuntimeOutboxEvent.created_at)  # type: ignore[arg-type]
        .limit(limit)
    )
    dialect = session.get_bind().dialect.name
    stmt = base.with_for_update(skip_locked=True) if dialect == 'postgresql' else base
    events = list(session.execute(stmt).scalars().all())
    dispatched = 0
    for event in events:
        try:
            runtime_ipc.notify_runtime_payload(dict(event.payload_json))
        except Exception as exc:  # noqa: BLE001 - outbox must preserve retry state for transport failures.
            _mark_failed(session, event, error=str(exc))
            continue
        event.status = RuntimeOutboxStatus.DISPATCHED
        event.attempts += 1
        event.last_error = None
        event.dispatched_at = _utcnow()
        event.updated_at = event.dispatched_at
        session.add(event)
        session.commit()
        dispatched += 1
    return dispatched


def pending_event_count(session: Session) -> int:
    table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    stmt = select(RuntimeOutboxEvent).where(table.c.status.in_([RuntimeOutboxStatus.PENDING, RuntimeOutboxStatus.FAILED]))
    return len(session.execute(stmt).scalars().all())


def _mark_failed(session: Session, event: RuntimeOutboxEvent, *, error: str) -> None:
    retry_at = _utcnow() + timedelta(seconds=settings.runtime_outbox_retry_seconds)
    event.status = RuntimeOutboxStatus.FAILED
    event.attempts += 1
    event.last_error = error[:1000]
    event.available_at = retry_at
    event.updated_at = _utcnow()
    session.add(event)
    session.commit()
