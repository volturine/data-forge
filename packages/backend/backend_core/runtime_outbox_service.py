import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text
from sqlmodel import Session

from backend_core import notification_delivery, runtime_ipc, runtime_work_service
from backend_core.claiming import with_for_update_skip_locked
from backend_core.config import settings
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.namespace import get_namespace
from backend_core.notification_delivery import redact_secrets_in_text
from backend_core.persistence.runtime_events.models import NotificationDeliveryReceipt, RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.runtime_work_service import RuntimeWorkKind
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
_OUTBOX_PENDING_QUERY = """
    SELECT 1
    FROM runtime_outbox_events
    WHERE (status IN ('pending', 'failed') AND available_at <= statement_timestamp())
       OR (
            status = 'dispatching'
            AND lease_expires_at <= statement_timestamp()
            AND available_at <= statement_timestamp()
       )
"""
_OUTBOX_DUE_QUERY = """
    SELECT min(next_attempt_at)
    FROM (
        SELECT available_at AS next_attempt_at
        FROM runtime_outbox_events
        WHERE status IN ('pending', 'failed')
        UNION ALL
        SELECT greatest(available_at, lease_expires_at) AS next_attempt_at
        FROM runtime_outbox_events
        WHERE status = 'dispatching' AND lease_expires_at IS NOT NULL
    ) AS scheduled_events
    WHERE next_attempt_at > statement_timestamp()
"""
OUTBOX_WAKE_KIND = 'runtime_outbox_wakeup'
_RUNTIME_EVENTS_CHANNEL = 'runtime_events'
_EXTERNAL_DELIVERY_KINDS = notification_delivery.EXTERNAL_DELIVERY_KINDS


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    event_id: str
    claim_token: str
    lease_generation: int
    event_kind: str
    payload: dict[str, object]
    already_delivered: bool = False


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
    payload_namespace = payload.get('namespace')
    namespace = payload_namespace if isinstance(payload_namespace, str) and payload_namespace else get_namespace()
    _mark_namespace_pending(session, namespace=namespace)
    _notify_dispatcher(session, namespace=namespace)
    return event


def enqueue_notification_delivery(session: Session, payload: dict[str, object]) -> RuntimeOutboxEvent:
    kind = payload.get('kind')
    if kind not in _EXTERNAL_DELIVERY_KINDS:
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
    namespace = get_namespace()
    _mark_namespace_pending(session, namespace=namespace)
    _notify_dispatcher(session, namespace=namespace)
    return event


def _notify_dispatcher(session: Session, *, namespace: str) -> None:
    """Wake API outbox dispatchers after this transaction commits.

    PostgreSQL delivers NOTIFY only after the surrounding transaction commits,
    so a rolled-back event cannot wake a dispatcher for work that does not
    exist. The five-second dispatcher poll remains the durable recovery path
    for a lost listener connection or an event committed during startup.
    SQLite-backed unit tests do not have PostgreSQL NOTIFY and simply use the
    direct request-path dispatchers.
    """
    bind = session.get_bind()
    if getattr(getattr(bind, 'dialect', None), 'name', None) != 'postgresql':
        return
    payload = json.dumps({'kind': OUTBOX_WAKE_KIND, 'namespace': namespace})
    session.execute(
        text('SELECT pg_notify(:channel, :payload)'),
        {'channel': _RUNTIME_EVENTS_CHANNEL, 'payload': payload},
    )


def _mark_namespace_pending(session: Session, *, namespace: str) -> None:
    """Persist a recovery hint in the same transaction as the outbox event."""
    runtime_work_service.append_wake(session, namespace=namespace, kind=RuntimeWorkKind.OUTBOX)


def list_pending_outbox_namespaces(session: Session) -> list[str]:
    """Read only namespaces with durable outbox work, using the public index."""
    return runtime_work_service.list_pending_namespaces(session, kinds=(RuntimeWorkKind.OUTBOX,))


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
    return enqueue_runtime_event(session, {'kind': RuntimePayloadKind.JOB.value, 'namespace': get_namespace()})


def enqueue_datasource_delete_notification(session: Session, *, datasource_id: str) -> RuntimeOutboxEvent:
    return enqueue_runtime_event(
        session,
        {
            'kind': RuntimePayloadKind.DATASOURCE_DELETE.value,
            'namespace': get_namespace(),
            'datasource_id': datasource_id,
        },
    )


def dispatch_pending_events(session: Session, *, limit: int = 1) -> int:
    """Dispatch runtime wakes; external deliveries have isolated consumers."""
    bind = session.get_bind()
    if settings.distributed_runtime_enabled and getattr(getattr(bind, 'dialect', None), 'name', None) == 'postgresql':
        return _dispatch_postgres_runtime_events(session, limit=max(int(limit), 0))

    dispatched = 0
    for _ in range(max(int(limit), 0)):
        claims = _claim_next_events(session, limit=1)
        if not claims:
            break
        claim = claims[0]
        try:
            runtime_ipc.notify_runtime_payload({**claim.payload, 'event_id': claim.event_id})
        except Exception as exc:  # noqa: BLE001 - outbox must preserve retry state for transport failures.
            _finalize_claims(session, [(claim, _redact_payload_secrets(str(exc), claim.payload))])
            continue
        finalized, _dispatched = _finalize_claims(session, [(claim, None)])
        if finalized:
            dispatched += 1
    _clear_namespace_pending_if_idle(session)
    session.commit()
    return dispatched


def _dispatch_postgres_runtime_events(session: Session, *, limit: int) -> int:
    """Claim runtime wakes in batches and commit each batch with its NOTIFYs."""
    dispatched = 0
    processed = 0
    while processed < limit:
        claims = _claim_next_events(session, limit=limit - processed)
        if not claims:
            break
        processed += len(claims)

        outcomes = [(claim, None) for claim in claims]
        try:
            _finalized, delivered = _finalize_claims(session, outcomes)
        except Exception as exc:  # noqa: BLE001 - roll back notify+finalize, then persist retry state.
            session.rollback()
            failures = [(claim, _redact_payload_secrets(str(exc), claim.payload)) for claim in claims]
            _finalized, delivered = _finalize_claims(session, failures)
        dispatched += delivered

    _clear_namespace_pending_if_idle(session)
    session.commit()
    return dispatched


def _clear_namespace_pending_if_idle(session: Session) -> None:
    """Clear a marker only after every active event in this tenant is gone."""
    runtime_work_service.refresh_pending_work(
        session,
        namespace=get_namespace(),
        kind=RuntimeWorkKind.OUTBOX,
        pending_query=_OUTBOX_PENDING_QUERY,
        due_query=_OUTBOX_DUE_QUERY,
    )


def claim_external_deliveries(session: Session, *, kind: str, limit: int = 1) -> list[OutboxClaim]:
    """Claim work for one provider lane; the caller closes the session before sending."""
    if kind not in _EXTERNAL_DELIVERY_KINDS:
        raise ValueError(f'Unsupported external delivery kind: {kind!r}')
    return _claim_next_events(session, limit=limit, event_kinds=(kind,))


def finalize_external_delivery(session: Session, claim: OutboxClaim, *, error: str | None = None) -> bool:
    """Persist a provider result only while its claim token and generation are current.

    Provider delivery and the receipt transaction cannot be atomic. A process
    failure after provider acceptance and before this commit can cause a retry.
    """
    redacted_error = _redact_payload_secrets(error, claim.payload) if error is not None else None
    finalized, _delivered = _finalize_claims(
        session,
        [(claim, redacted_error)],
        record_external_receipt=error is None and not claim.already_delivered,
    )
    if finalized:
        _clear_namespace_pending_if_idle(session)
        session.commit()
    return finalized == 1


def _claim_next_events(
    session: Session,
    *,
    limit: int,
    event_kinds: Sequence[str] | None = None,
) -> list[OutboxClaim]:
    if limit < 1:
        return []
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
        .limit(limit)
    )
    base = base.where(table.c.kind.not_in(_EXTERNAL_DELIVERY_KINDS)) if event_kinds is None else base.where(table.c.kind.in_(event_kinds))
    stmt = with_for_update_skip_locked(session, base)
    events = list(session.execute(stmt).scalars().all())
    if not events:
        session.rollback()
        return []

    claims: list[OutboxClaim] = []
    for event in events:
        claim_token = str(uuid.uuid4())
        event.status = RuntimeOutboxStatus.DISPATCHING
        event.claim_token = claim_token
        event.lease_generation += 1
        event.lease_expires_at = now + timedelta(seconds=settings.runtime_outbox_claim_ttl_seconds)
        event.attempts += 1
        event.updated_at = now
        claims.append(
            OutboxClaim(
                event_id=event.id,
                claim_token=claim_token,
                lease_generation=event.lease_generation,
                event_kind=event.kind,
                payload=dict(event.payload_json),
                already_delivered=(event.kind in _EXTERNAL_DELIVERY_KINDS and session.get(NotificationDeliveryReceipt, event.id) is not None),
            )
        )
        session.add(event)
    session.commit()
    return claims


def _claim_next_event(session: Session) -> tuple[str, str, int, str, dict[str, object]] | None:
    claims = _claim_next_events(session, limit=1)
    if not claims:
        return None
    claim = claims[0]
    return claim.event_id, claim.claim_token, claim.lease_generation, claim.event_kind, claim.payload


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
    claim = OutboxClaim(
        event_id=event_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        event_kind='',
        payload={},
    )
    finalized, _dispatched = _finalize_claims(session, [(claim, error)])
    return finalized == 1


def _finalize_claims(
    session: Session,
    outcomes: Sequence[tuple[OutboxClaim, str | None]],
    *,
    record_external_receipt: bool = False,
) -> tuple[int, int]:
    if not outcomes:
        return 0, 0

    now = _database_now(session)
    table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    claims_by_id = {claim.event_id: (claim, error) for claim, error in outcomes}
    statement = select(RuntimeOutboxEvent).where(table.c.id.in_(claims_by_id)).where(table.c.status == RuntimeOutboxStatus.DISPATCHING).with_for_update()
    events = list(session.execute(statement).scalars().all())
    finalized = 0
    dispatched = 0
    for event in events:
        claim, error = claims_by_id[event.id]
        if event.claim_token != claim.claim_token or event.lease_generation != claim.lease_generation:
            continue
        if error is None and event.kind not in _EXTERNAL_DELIVERY_KINDS:
            runtime_ipc.notify_runtime_payload_on_commit(session, {**event.payload_json, 'event_id': event.id})
        if record_external_receipt and error is None and event.kind in _EXTERNAL_DELIVERY_KINDS:
            receipt = session.get(NotificationDeliveryReceipt, event.id)
            if receipt is None:
                session.add(NotificationDeliveryReceipt(event_id=event.id, kind=event.kind, delivered_at=now))
        poisoned = error is not None and event.attempts >= settings.runtime_outbox_max_attempts
        event.status = RuntimeOutboxStatus.DISPATCHED if error is None else RuntimeOutboxStatus.POISONED if poisoned else RuntimeOutboxStatus.FAILED
        event.claim_token = None
        event.lease_expires_at = None
        event.last_error = error[:1000] if error is not None else None
        event.available_at = now + timedelta(seconds=settings.runtime_outbox_retry_seconds) if error is not None and not poisoned else now
        event.dispatched_at = now if error is None else None
        event.updated_at = now
        session.add(event)
        finalized += 1
        if error is None:
            dispatched += 1
    if finalized == 0:
        session.rollback()
        return 0, 0
    session.commit()
    return finalized, dispatched
