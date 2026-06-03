from datetime import UTC, datetime

from contracts.runtime.events import RuntimePayloadKind
from core import runtime_outbox_service
from persistence.runtime_events.models import RuntimeOutboxStatus


def test_dispatch_pending_events_marks_event_dispatched(test_db_session, monkeypatch) -> None:
    payloads: list[dict[str, object]] = []
    event = runtime_outbox_service.enqueue_build_job_notification(test_db_session)

    monkeypatch.setattr('core.runtime_outbox_service.runtime_ipc.notify_runtime_payload', lambda payload: payloads.append(payload))

    dispatched = runtime_outbox_service.dispatch_pending_events(test_db_session)

    test_db_session.refresh(event)
    assert dispatched == 1
    assert event.status == RuntimeOutboxStatus.DISPATCHED
    assert event.dispatched_at is not None
    assert payloads == [{'kind': RuntimePayloadKind.JOB.value}]


def test_dispatch_pending_events_keeps_failed_event_retryable(test_db_session, monkeypatch) -> None:
    event = runtime_outbox_service.enqueue_build_job_notification(test_db_session)

    def fail(_payload: dict[str, object]) -> None:
        raise RuntimeError('transport down')

    monkeypatch.setattr('core.runtime_outbox_service.runtime_ipc.notify_runtime_payload', fail)

    dispatched = runtime_outbox_service.dispatch_pending_events(test_db_session)

    test_db_session.refresh(event)
    assert dispatched == 0
    assert event.status == RuntimeOutboxStatus.FAILED
    assert event.attempts == 1
    assert event.last_error == 'transport down'
    assert event.available_at > datetime.now(UTC)
