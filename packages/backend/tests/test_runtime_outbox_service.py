from datetime import UTC, datetime, timedelta

from backend_core import runtime_outbox_service
from backend_core.config import settings
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.notification_delivery import EMAIL_DELIVERY_KIND
from backend_core.persistence.runtime_events.models import RuntimeOutboxStatus


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
    assert payloads == [{'kind': RuntimePayloadKind.JOB.value, 'event_id': event.id}]


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


def test_dispatch_notification_delivery_uses_stable_outbox_id(test_db_session, monkeypatch) -> None:
    deliveries: list[tuple[dict[str, object], str]] = []
    event = runtime_outbox_service.enqueue_notification_delivery(
        test_db_session,
        {'kind': EMAIL_DELIVERY_KIND, 'to': 'test@example.com', 'subject': 'Ready', 'body': 'Done', 'attachments': []},
    )
    monkeypatch.setattr(
        'backend_core.runtime_outbox_service.notification_delivery.deliver',
        lambda payload, *, event_id: deliveries.append((payload, event_id)),
    )

    assert runtime_outbox_service.dispatch_pending_events(test_db_session) == 1
    assert deliveries == [({**event.payload_json, 'event_id': event.id}, event.id)]


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
