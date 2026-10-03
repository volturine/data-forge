from datetime import UTC, datetime, timedelta

from backend_core import runtime_outbox_service
from backend_core.config import settings
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.notification_delivery import EMAIL_DELIVERY_KIND, TELEGRAM_DELIVERY_KIND
from backend_core.persistence.runtime_events.models import (
    NotificationDeliveryPartReceipt,
    NotificationDeliveryReceipt,
    RuntimeOutboxStatus,
)


def test_dispatch_pending_events_marks_event_dispatched(test_db_session, monkeypatch) -> None:
    payloads: list[dict[str, object]] = []
    event = runtime_outbox_service.enqueue_build_job_notification(test_db_session)

    monkeypatch.setattr('backend_core.runtime_outbox_service.runtime_ipc.notify_runtime_payload', lambda payload: payloads.append(payload))

    dispatched = runtime_outbox_service.dispatch_pending_events(test_db_session)

    test_db_session.refresh(event)
    assert dispatched == 1
    assert event.status == RuntimeOutboxStatus.DISPATCHED
    assert event.dispatched_at is not None
    assert event.claim_token is None
    assert event.lease_expires_at is None
    assert event.lease_generation == 1
    assert payloads == [{'kind': RuntimePayloadKind.JOB.value, 'namespace': 'default', 'event_id': event.id}]


def test_dispatch_pending_events_keeps_failed_event_retryable(test_db_session, monkeypatch) -> None:
    event = runtime_outbox_service.enqueue_build_job_notification(test_db_session)

    def fail(_payload: dict[str, object]) -> None:
        raise RuntimeError('transport down')

    monkeypatch.setattr('backend_core.runtime_outbox_service.runtime_ipc.notify_runtime_payload', fail)

    dispatched = runtime_outbox_service.dispatch_pending_events(test_db_session)

    test_db_session.refresh(event)
    assert dispatched == 0
    assert event.status == RuntimeOutboxStatus.FAILED
    assert event.attempts == 1
    assert event.last_error == 'transport down'
    assert event.available_at > datetime.now(UTC)


def test_dispatch_pending_events_quarantines_poison_event(test_db_session, monkeypatch) -> None:
    event = runtime_outbox_service.enqueue_build_job_notification(test_db_session)
    monkeypatch.setattr(settings, 'runtime_outbox_max_attempts', 1)

    def reject(_payload: dict[str, object]) -> None:
        raise RuntimeError('invalid payload')

    monkeypatch.setattr('backend_core.runtime_outbox_service.runtime_ipc.notify_runtime_payload', reject)

    assert runtime_outbox_service.dispatch_pending_events(test_db_session) == 0

    test_db_session.refresh(event)
    assert event.status == RuntimeOutboxStatus.POISONED
    assert event.attempts == 1
    assert runtime_outbox_service.pending_event_count(test_db_session) == 0


def test_runtime_dispatch_leaves_external_delivery_for_its_lane(test_db_session, monkeypatch) -> None:
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': TELEGRAM_DELIVERY_KIND, 'chat_id': '123', 'message': 'Ready', 'bot_token': '12345:SECRET-TOKEN', 'attachments': []},
    )
    test_db_session.commit()
    monkeypatch.setattr('backend_core.runtime_outbox_service.runtime_ipc.notify_runtime_payload', lambda _payload: None)

    dispatched = runtime_outbox_service.dispatch_pending_events(test_db_session)

    test_db_session.refresh(event)
    assert dispatched == 0
    assert event.status == RuntimeOutboxStatus.PENDING
    assert event.attempts == 0

    claims = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=TELEGRAM_DELIVERY_KIND)

    test_db_session.refresh(event)
    assert [claim.event_id for claim in claims] == [event.id]
    assert event.status == RuntimeOutboxStatus.DISPATCHING
    assert event.attempts == 1


def test_external_claim_delivery_uses_stable_outbox_id_and_records_receipt(test_db_session, monkeypatch) -> None:
    deliveries: list[tuple[dict[str, object], str]] = []
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': EMAIL_DELIVERY_KIND, 'to': 'test@example.com', 'subject': 'Ready', 'body': 'Done', 'attachments': []},
    )
    test_db_session.commit()
    claims = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=EMAIL_DELIVERY_KIND)
    assert len(claims) == 1
    claim = claims[0]
    monkeypatch.setattr(
        'backend_core.runtime_integration_delivery.notification_delivery.deliver',
        lambda payload, *, event_id: deliveries.append((payload, event_id)),
    )

    from backend_core import notification_delivery

    notification_delivery.deliver({**claim.payload, 'event_id': claim.event_id}, event_id=claim.event_id)
    assert runtime_outbox_service.finalize_external_delivery(test_db_session, claim)
    assert deliveries == [({**event.payload_json, 'event_id': event.id}, event.id)]
    receipt = test_db_session.get(NotificationDeliveryReceipt, event.id)
    assert receipt is not None
    assert receipt.kind == EMAIL_DELIVERY_KIND


def test_external_claim_detects_prior_receipt_without_redelivering(test_db_session) -> None:
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': EMAIL_DELIVERY_KIND, 'to': 'test@example.com', 'subject': 'Ready', 'body': 'Done', 'attachments': []},
    )
    test_db_session.commit()
    test_db_session.add(NotificationDeliveryReceipt(event_id=event.id, kind=EMAIL_DELIVERY_KIND, delivered_at=datetime.now(UTC)))
    event.status = RuntimeOutboxStatus.FAILED
    test_db_session.add(event)
    test_db_session.commit()

    claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=EMAIL_DELIVERY_KIND)[0]
    assert claim.already_delivered
    assert runtime_outbox_service.finalize_external_delivery(test_db_session, claim)


def test_external_claim_filters_by_provider_kind(test_db_session) -> None:
    email = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': EMAIL_DELIVERY_KIND, 'to': 'test@example.com', 'subject': 'Ready', 'body': 'Done'},
    )
    telegram = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': TELEGRAM_DELIVERY_KIND, 'chat_id': '123', 'message': 'Ready'},
    )
    test_db_session.commit()

    email_claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=EMAIL_DELIVERY_KIND)[0]
    assert email_claim.event_id == email.id
    telegram_claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=TELEGRAM_DELIVERY_KIND)[0]
    assert telegram_claim.event_id == telegram.id


def test_external_delivery_failure_is_redacted_and_retryable(test_db_session) -> None:
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': TELEGRAM_DELIVERY_KIND, 'chat_id': '123', 'message': 'Ready', 'bot_token': '12345:SECRET-TOKEN', 'attachments': []},
    )
    test_db_session.commit()
    claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=TELEGRAM_DELIVERY_KIND)[0]

    assert runtime_outbox_service.finalize_external_delivery(
        test_db_session,
        claim,
        error='request to https://api.telegram.org/bot12345:SECRET-TOKEN/sendMessage failed',
    )

    test_db_session.refresh(event)
    assert event.status == RuntimeOutboxStatus.FAILED
    assert event.last_error == 'request to https://api.telegram.org/bot[REDACTED]/sendMessage failed'
    assert '12345:SECRET-TOKEN' not in (event.last_error or '')
    assert event.available_at > datetime.now(UTC)


def test_telegram_delivery_progress_survives_retry_and_rejects_stale_claim(test_db_session) -> None:
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': TELEGRAM_DELIVERY_KIND, 'chat_id': '123', 'message': 'Ready', 'attachments': [{'filename': 'one.csv'}]},
    )
    test_db_session.commit()
    first_claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=TELEGRAM_DELIVERY_KIND)[0]

    assert first_claim.completed_parts == frozenset()
    assert runtime_outbox_service.record_external_delivery_part(test_db_session, first_claim, part_key='message')
    assert test_db_session.get(NotificationDeliveryPartReceipt, (event.id, 'message')) is not None

    event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(event)
    test_db_session.commit()
    retry_claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=TELEGRAM_DELIVERY_KIND)[0]

    assert retry_claim.claim_token != first_claim.claim_token
    assert retry_claim.completed_parts == frozenset({'message'})
    assert not runtime_outbox_service.record_external_delivery_part(test_db_session, first_claim, part_key='attachment:0')
    assert runtime_outbox_service.record_external_delivery_part(test_db_session, retry_claim, part_key='attachment:0')
    assert runtime_outbox_service.finalize_external_delivery(test_db_session, retry_claim)

    test_db_session.refresh(event)
    assert event.status == RuntimeOutboxStatus.DISPATCHED
    assert test_db_session.get(NotificationDeliveryPartReceipt, (event.id, 'message')) is None
    assert test_db_session.get(NotificationDeliveryPartReceipt, (event.id, 'attachment:0')) is None
    assert test_db_session.get(NotificationDeliveryReceipt, event.id) is not None


def test_external_delivery_finalization_rejects_stale_lease(test_db_session) -> None:
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': EMAIL_DELIVERY_KIND, 'to': 'test@example.com', 'subject': 'Ready', 'body': 'Done'},
    )
    test_db_session.commit()
    first_claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=EMAIL_DELIVERY_KIND)[0]

    test_db_session.refresh(event)
    event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(event)
    test_db_session.commit()
    second_claim = runtime_outbox_service.claim_external_deliveries(test_db_session, kind=EMAIL_DELIVERY_KIND)[0]

    assert second_claim.claim_token != first_claim.claim_token
    assert second_claim.lease_generation == first_claim.lease_generation + 1
    assert not runtime_outbox_service.finalize_external_delivery(test_db_session, first_claim)
    assert runtime_outbox_service.finalize_external_delivery(test_db_session, second_claim)


def test_expired_dispatch_claim_is_reclaimed_and_stale_finalizer_is_rejected(test_db_session) -> None:
    event = runtime_outbox_service.enqueue_build_job_notification(test_db_session)
    first_claim = runtime_outbox_service._claim_next_event(test_db_session)
    assert first_claim is not None
    event_id, first_token, first_generation, _, _ = first_claim

    test_db_session.refresh(event)
    event.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(event)
    test_db_session.commit()

    second_claim = runtime_outbox_service._claim_next_event(test_db_session)
    assert second_claim is not None
    _, second_token, second_generation, _, _ = second_claim
    assert second_token != first_token
    assert second_generation == first_generation + 1

    stale_applied = runtime_outbox_service._finalize_claim(
        test_db_session,
        event_id,
        claim_token=first_token,
        lease_generation=first_generation,
        error=None,
    )
    assert stale_applied is False

    current_applied = runtime_outbox_service._finalize_claim(
        test_db_session,
        event_id,
        claim_token=second_token,
        lease_generation=second_generation,
        error=None,
    )
    assert current_applied is True
    test_db_session.refresh(event)
    assert event.status == RuntimeOutboxStatus.DISPATCHED
    assert event.attempts == 2
