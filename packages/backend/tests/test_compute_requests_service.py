from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from backend_core import compute_requests_service
from backend_core.domain.compute_requests.models import command_envelope_from_json
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from dataforge_protocol import enums_pb2


def test_claim_next_request_prioritizes_user_create_requests_over_previews(test_db_session) -> None:
    create_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload'},
    )
    preview = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json={'name': 'preview'},
    )

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is not None
    assert claimed.id == create_request.id
    assert claimed.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert claimed.lease_expires_at is not None

    remaining = compute_requests_service.get_request(test_db_session, preview.id)
    assert remaining is not None
    assert remaining.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


def test_claim_next_request_prioritizes_user_create_requests_over_background_ingest(test_db_session) -> None:
    background = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        request_json={'name': 'background'},
    )
    create_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload'},
    )

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is not None
    assert claimed.id == create_request.id
    assert claimed.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING

    remaining = compute_requests_service.get_request(test_db_session, background.id)
    assert remaining is not None
    assert remaining.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


def test_mark_request_failed_recovers_from_pending_rollback(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, request_json={'example': True}
    )
    request_id = request.id

    duplicate = (
        ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
        .insert()
        .values(
            id=request_id,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
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

    assert failed.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert failed.error_message == 'boom'
    assert failed.response_json is not None
    assert failed.response_json['kind'] == 'COMPUTE_REQUEST_KIND_PREVIEW'
    assert failed.response_json['version'] == 1
    assert failed.response_json['correlation_id'] == request_id
    assert failed.response_json['status'] == 'COMPUTE_REQUEST_STATUS_FAILED'
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
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        request_json={
            'engine_identity': {
                'scope': 'analysis_interactive',
                'reuse_policy': 'shared',
                'resource_id': 'analysis-1',
                'analysis_id': 'analysis-1',
            },
            'resource_config': {'max_threads': 4, 'max_memory_mb': 512},
        },
    )

    assert request.request_json['kind'] == 'COMPUTE_REQUEST_KIND_SPAWN_ENGINE'
    assert request.request_json['version'] == 1
    assert request.request_json['idempotency_key'] == request.id
    assert request.request_json['correlation_id'] == request.id
    assert compute_requests_service.command_payload(request)['engine_identity'] == {
        'analysis_id': 'analysis-1',
        'resource_id': 'analysis-1',
        'reuse_policy': 'shared',
        'scope': 'analysis_interactive',
    }
    envelope = command_envelope_from_json(request.request_json)
    assert envelope.command.WhichOneof('command') == 'spawn_engine'
    assert envelope.command.spawn_engine.engine_identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert envelope.command.spawn_engine.resource_config.max_memory_mb == 512


def test_mark_request_completed_stores_typed_response_envelope(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json={'example': True},
    )

    completed = compute_requests_service.mark_request_completed(test_db_session, request.id, response_json={'rows': [{'id': 1}]})

    assert completed.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    assert completed.response_json is not None
    assert completed.response_json['kind'] == 'COMPUTE_REQUEST_KIND_PREVIEW'
    assert completed.response_json['version'] == 1
    assert completed.response_json['correlation_id'] == request.id
    assert completed.response_json['status'] == 'COMPUTE_REQUEST_STATUS_COMPLETED'
    assert 'error_message' not in completed.response_json
    assert compute_requests_service.response_payload(completed) == {'rows': [{'id': 1}]}
    outbox_event = test_db_session.execute(select(RuntimeOutboxEvent)).scalars().one()
    assert outbox_event.kind == RuntimePayloadKind.COMPUTE_RESPONSE.value
    assert outbox_event.status == RuntimeOutboxStatus.PENDING
    assert outbox_event.payload_json == {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request.id}


def test_claim_next_request_reclaims_expired_lease(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json={'example': True},
    )
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    request.lease_owner = 'live-worker'
    request.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(request)
    test_db_session.commit()

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2')

    assert claimed is not None
    assert claimed.id == request.id
    assert claimed.lease_owner == 'worker-2'
    assert claimed.lease_expires_at is not None
