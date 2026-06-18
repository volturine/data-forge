from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from backend_core import compute_requests_service
from backend_core.domain.compute_requests.models import ComputeRequestKind, ComputeRequestStatus
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus


def test_claim_next_request_prioritizes_user_create_requests_over_previews(test_db_session) -> None:
    create_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload'},
    )
    preview = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.PREVIEW,
        request_json={'name': 'preview'},
    )

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is not None
    assert claimed.id == create_request.id
    assert claimed.status == ComputeRequestStatus.RUNNING
    assert claimed.lease_expires_at is not None

    remaining = compute_requests_service.get_request(test_db_session, preview.id)
    assert remaining is not None
    assert remaining.status == ComputeRequestStatus.QUEUED


def test_claim_next_request_prioritizes_user_create_requests_over_background_ingest(test_db_session) -> None:
    background = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.INGEST_DATASOURCE,
        request_json={'name': 'background'},
    )
    create_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload'},
    )

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is not None
    assert claimed.id == create_request.id
    assert claimed.status == ComputeRequestStatus.RUNNING

    remaining = compute_requests_service.get_request(test_db_session, background.id)
    assert remaining is not None
    assert remaining.status == ComputeRequestStatus.QUEUED


def test_mark_request_failed_recovers_from_pending_rollback(test_db_session) -> None:
    request = compute_requests_service.create_request(test_db_session, namespace='default', kind=ComputeRequestKind.PREVIEW, request_json={'example': True})
    request_id = request.id

    duplicate = (
        ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
        .insert()
        .values(
            id=request_id,
            namespace='default',
            kind=ComputeRequestKind.PREVIEW,
            status=ComputeRequestStatus.QUEUED,
            request_json={'duplicate': True},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        test_db_session.execute(duplicate)
        test_db_session.commit()

    failed = compute_requests_service.mark_request_failed(
        test_db_session, request_id, error_message='boom', response_json={'error': 'boom', 'status_code': 500}
    )

    assert failed.status == ComputeRequestStatus.FAILED
    assert failed.error_message == 'boom'
    assert failed.response_json is not None
    assert failed.response_json['kind'] == ComputeRequestKind.PREVIEW.value
    assert failed.response_json['version'] == 1
    assert failed.response_json['correlation_id'] == request_id
    assert failed.response_json['status'] == ComputeRequestStatus.FAILED.value
    assert failed.response_json['error_message'] == 'boom'
    assert compute_requests_service.response_payload(failed) == {'error': 'boom', 'status_code': 500}
    outbox_event = test_db_session.execute(select(RuntimeOutboxEvent)).scalars().one()
    assert outbox_event.kind == RuntimePayloadKind.COMPUTE_RESPONSE.value
    assert outbox_event.status == RuntimeOutboxStatus.PENDING
    assert outbox_event.payload_json == {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request_id}
    assert failed.completed_at is not None


def test_create_request_stores_typed_command_envelope(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.PREVIEW,
        request_json={'example': True},
    )

    assert request.request_json['kind'] == ComputeRequestKind.PREVIEW.value
    assert request.request_json['version'] == 1
    assert request.request_json['idempotency_key'] == request.id
    assert request.request_json['correlation_id'] == request.id
    assert compute_requests_service.command_payload(request) == {'example': True}


def test_mark_request_completed_stores_typed_response_envelope(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.PREVIEW,
        request_json={'example': True},
    )

    completed = compute_requests_service.mark_request_completed(test_db_session, request.id, response_json={'rows': [{'id': 1}]})

    assert completed.status == ComputeRequestStatus.COMPLETED
    assert completed.response_json is not None
    assert completed.response_json['kind'] == ComputeRequestKind.PREVIEW.value
    assert completed.response_json['version'] == 1
    assert completed.response_json['correlation_id'] == request.id
    assert completed.response_json['status'] == ComputeRequestStatus.COMPLETED.value
    assert completed.response_json['error_message'] is None
    assert compute_requests_service.response_payload(completed) == {'rows': [{'id': 1}]}
    outbox_event = test_db_session.execute(select(RuntimeOutboxEvent)).scalars().one()
    assert outbox_event.kind == RuntimePayloadKind.COMPUTE_RESPONSE.value
    assert outbox_event.status == RuntimeOutboxStatus.PENDING
    assert outbox_event.payload_json == {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request.id}


def test_claim_next_request_reclaims_expired_lease(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=ComputeRequestKind.PREVIEW,
        request_json={'example': True},
    )
    request.status = ComputeRequestStatus.RUNNING
    request.lease_owner = 'live-worker'
    request.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(request)
    test_db_session.commit()

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2')

    assert claimed is not None
    assert claimed.id == request.id
    assert claimed.lease_owner == 'worker-2'
    assert claimed.lease_expires_at is not None
