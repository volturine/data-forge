import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlmodel import Session

from backend_core import notification_delivery, runtime_ipc
from backend_core.claiming import with_for_update_skip_locked
from backend_core.config import settings
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.notification_delivery import redact_secrets_in_text
from backend_core.persistence.runtime_events.models import NotificationDeliveryReceipt, RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.sqlmodel_typing import sa
from backend_core.transactions import committed

_SENSITIVE_ERROR_FIELDS = frozenset(
    {
        'password',
        'smtp_password',
        'telegram_bot_token',
        'openrouter_api_key',
        'openai_api_key',
        'kaggle_api_key',
        'api_key',
        'authorization',
        'bot_token',
        'token',
    }
)


def _redact_payload_secrets(message: str, payload: dict[str, object]) -> str:
    secrets = [str(value) for key, value in payload.items() if key in _SENSITIVE_ERROR_FIELDS and isinstance(value, str) and value]
    return redact_secrets_in_text(message, *secrets)


def _database_now(session: Session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise TypeError('Database CURRENT_TIMESTAMP did not return a datetime')
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def enqueue_runtime_event(session: Session, payload: dict[str, object]) -> RuntimeOutboxEvent:
    kind = RuntimePayloadKind.from_payload(payload)
    if kind is None:
        raise ValueError(f'Unsupported runtime outbox payload kind: {payload.get("kind")!r}')
    now = _database_now(session)
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
    session.flush()
    return event


def enqueue_notification_delivery(session: Session, payload: dict[str, object]) -> RuntimeOutboxEvent:
    kind = payload.get('kind')
    if kind not in {notification_delivery.EMAIL_DELIVERY_KIND, notification_delivery.TELEGRAM_DELIVERY_KIND}:
        raise ValueError(f'Unsupported notification delivery kind: {kind!r}')
    now = _database_now(session)
    event = RuntimeOutboxEvent(
        id=str(uuid.uuid4()),
        kind=str(kind),
        status=RuntimeOutboxStatus.PENDING,
        payload_json=dict(payload),
        attempts=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(event)
    session.flush()
    return event


enqueue_notification_delivery_command = committed(enqueue_notification_delivery, refresh=True)


def enqueue_api_build_notification(session: Session, *, namespace: str, build_id: str, latest_sequence: int) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {
            'kind': RuntimePayloadKind.BUILD.value,
            'namespace': namespace,
            'build_id': build_id,
            'latest_sequence': latest_sequence,
        },
    )


def enqueue_build_job_notification(session: Session) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(session, {'kind': RuntimePayloadKind.JOB.value})


def enqueue_compute_request_notification(session: Session, *, request_id: str) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {'kind': RuntimePayloadKind.COMPUTE_REQUEST.value, 'request_id': request_id},
    )


def enqueue_compute_response_notification(session: Session, *, request_id: str) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request_id},
    )


def dispatch_pending_events(session: Session, *, limit: int = 100) -> int:
    dispatched = 0
    for _ in range(limit):
        claim = _claim_next_event(session)
        if claim is None:
            break
        event_id, claim_token, lease_generation, event_kind, payload = claim
        delivery_payload = {**payload, 'event_id': event_id}
        try:
            if event_kind in {notification_delivery.EMAIL_DELIVERY_KIND, notification_delivery.TELEGRAM_DELIVERY_KIND}:
                if not _notification_was_delivered(session, event_id):
                    notification_delivery.deliver(delivery_payload, event_id=event_id)
                    _record_notification_delivery(session, event_id=event_id, kind=event_kind)
            else:
                runtime_ipc.notify_runtime_payload(delivery_payload)
        except Exception as exc:  # noqa: BLE001 - outbox must preserve retry state for transport failures.
            _finalize_claim(
                session,
                event_id,
                claim_token=claim_token,
                lease_generation=lease_generation,
                error=_redact_payload_secrets(str(exc), payload),
            )
            continue
        if _finalize_claim(session, event_id, claim_token=claim_token, lease_generation=lease_generation, error=None):
            dispatched += 1
    return dispatched


def _notification_was_delivered(session: Session, event_id: str) -> bool:
    return session.get(NotificationDeliveryReceipt, event_id) is not None


def _record_notification_delivery(session: Session, *, event_id: str, kind: str) -> None:
    if _notification_was_delivered(session, event_id):
        return
    session.add(NotificationDeliveryReceipt(event_id=event_id, kind=kind, delivered_at=_database_now(session)))
    session.commit()


def _claim_next_event(session: Session) -> tuple[str, str, int, str, dict[str, object]] | None:
    now = _database_now(session)
    table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    base = (
        select(RuntimeOutboxEvent)
        .where(
            or_(
                table.c.status.in_([RuntimeOutboxStatus.PENDING, RuntimeOutboxStatus.FAILED]),
                (table.c.status == RuntimeOutboxStatus.DISPATCHING) & (table.c.lease_expires_at <= now),
            )
        )
        .where(sa(RuntimeOutboxEvent.available_at <= now))
        .order_by(sa(RuntimeOutboxEvent.available_at), sa(RuntimeOutboxEvent.created_at), sa(RuntimeOutboxEvent.id))
        .limit(1)
    )
    stmt = with_for_update_skip_locked(session, base)
    event = session.execute(stmt).scalars().first()
    if event is None:
        session.rollback()
        return None
    claim_token = str(uuid.uuid4())
    event.status = RuntimeOutboxStatus.DISPATCHING
    event.claim_token = claim_token
    event.lease_generation += 1
    event.lease_expires_at = now + timedelta(seconds=settings.runtime_outbox_claim_ttl_seconds)
    event.attempts += 1
    event.updated_at = now
    session.add(event)
    session.commit()
    return event.id, claim_token, event.lease_generation, event.kind, dict(event.payload_json)


def pending_event_count(session: Session) -> int:
    table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    stmt = (
        select(func.count())
        .select_from(table)
        .where(table.c.status.in_([RuntimeOutboxStatus.PENDING, RuntimeOutboxStatus.FAILED, RuntimeOutboxStatus.DISPATCHING]))
    )
    return session.execute(stmt).scalar_one()


def _finalize_claim(
    session: Session,
    event_id: str,
    *,
    claim_token: str,
    lease_generation: int,
    error: str | None,
) -> bool:
    now = _database_now(session)
    table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    statement = (
        select(RuntimeOutboxEvent)
        .where(table.c.id == event_id)
        .where(table.c.status == RuntimeOutboxStatus.DISPATCHING)
        .where(table.c.claim_token == claim_token)
        .where(table.c.lease_generation == lease_generation)
        .with_for_update()
    )
    event = session.execute(statement).scalars().first()
    if event is None:
        session.rollback()
        return False
    poisoned = error is not None and event.attempts >= settings.runtime_outbox_max_attempts
    event.status = RuntimeOutboxStatus.DISPATCHED if error is None else RuntimeOutboxStatus.POISONED if poisoned else RuntimeOutboxStatus.FAILED
    event.claim_token = None
    event.lease_expires_at = None
    event.last_error = error[:1000] if error is not None else None
    event.available_at = now + timedelta(seconds=settings.runtime_outbox_retry_seconds) if error is not None and not poisoned else now
    event.dispatched_at = now if error is None else None
    event.updated_at = now
    session.add(event)
    session.commit()
    return True
