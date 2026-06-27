from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from backend_core import compute_requests_service
from backend_core.domain.compute_requests.models import (
    command_envelope_from_json,
    command_payload,
    dict_to_struct,
    response_envelope_from_json,
    response_payload,
)
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from dataforge_protocol import compute_pb2, enums_pb2, errors_pb2


def _preview_payload() -> dict[str, object]:
    return {
        'analysis_id': 'analysis-1',
        'target_step_id': 'source',
        'row_limit': 100,
        'page': 1,
        'analysis_pipeline': {
            'analysis_id': 'analysis-1',
            'tabs': [
                {
                    'id': 'tab-1',
                    'datasource': {'id': 'datasource-1', 'analysis_tab_id': 'tab-1', 'source_type': 'file', 'config': {'branch': 'main'}},
                    'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                    'steps': [],
                }
            ],
        },
    }


def test_claim_next_request_prioritizes_user_create_requests_over_previews(test_db_session) -> None:
    create_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload', 'file_path': 's3://data/upload.csv', 'file_type': 'csv', 'options': {}},
    )
    preview = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
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
        request_json={'datasource_id': 'background'},
    )
    create_request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload', 'file_path': 's3://data/upload.csv', 'file_type': 'csv', 'options': {}},
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
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, request_json=_preview_payload()
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
    response_envelope = response_envelope_from_json(failed.response_json)
    assert response_envelope.response.WhichOneof('response') == 'error'
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
    assert envelope.command.spawn_engine.engine_identity.resource_id == 'analysis-1'
    assert envelope.command.spawn_engine.resource_config.max_memory_mb == 512


def test_create_preview_request_stores_typed_command_envelope(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )

    envelope = command_envelope_from_json(request.request_json)

    assert envelope.command.WhichOneof('command') == 'preview'
    assert envelope.command.preview.target_step_id == 'source'
    assert envelope.command.preview.analysis_pipeline.analysis_id == 'analysis-1'
    assert envelope.command.preview.analysis_pipeline.tabs[0].datasource.source_type == enums_pb2.DATA_SOURCE_TYPE_FILE


def test_create_preview_request_converts_ai_provider_token(test_db_session) -> None:
    payload = _preview_payload()
    analysis_pipeline = payload['analysis_pipeline']
    assert isinstance(analysis_pipeline, dict)
    tabs = analysis_pipeline['tabs']
    assert isinstance(tabs, list)
    tab = tabs[0]
    assert isinstance(tab, dict)
    tab['steps'] = [
        {
            'id': 'ai-1',
            'type': 'ai',
            'config': {
                'provider': 'ollama',
                'model': 'llama3.2',
                'input_columns': [],
                'output_column': 'ai_result',
                'error_column': 'ai_error',
                'prompt_template': 'Classify',
                'batch_size': 10,
                'max_retries': 3,
                'endpoint_url': '',
                'api_key': '',
                'temperature': 0.7,
            },
            'depends_on': [],
        }
    ]
    payload['target_step_id'] = 'ai-1'

    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=payload,
    )

    envelope = command_envelope_from_json(request.request_json)

    assert envelope.command.preview.analysis_pipeline.tabs[0].steps[0].config.ai.provider == enums_pb2.AI_PROVIDER_OLLAMA


def test_create_preview_request_populates_protocol_step_type(test_db_session) -> None:
    payload = _preview_payload()
    analysis_pipeline = payload['analysis_pipeline']
    assert isinstance(analysis_pipeline, dict)
    tabs = analysis_pipeline['tabs']
    assert isinstance(tabs, list)
    tab = tabs[0]
    assert isinstance(tab, dict)
    tab['steps'] = [
        {
            'id': 'plot-1',
            'type': 'plot_scatter',
            'config': {'x_column': 'age', 'y_column': 'score'},
            'depends_on': [],
        }
    ]
    payload['target_step_id'] = 'plot-1'

    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=payload,
    )

    envelope = command_envelope_from_json(request.request_json)
    step = envelope.command.preview.analysis_pipeline.tabs[0].steps[0]

    assert step.type == 'plot_scatter'
    assert step.step_type == enums_pb2.STEP_TYPE_PLOT_SCATTER
    assert step.config.WhichOneof('config') == 'chart'
    command_payload = compute_requests_service.command_payload(request)
    command_pipeline = command_payload['analysis_pipeline']
    assert isinstance(command_pipeline, dict)
    command_tabs = command_pipeline['tabs']
    assert isinstance(command_tabs, list)
    command_tab = command_tabs[0]
    assert isinstance(command_tab, dict)
    command_steps = command_tab['steps']
    assert isinstance(command_steps, list)
    command_step = command_steps[0]
    assert isinstance(command_step, dict)
    assert command_step['step_type'] == 'plot_scatter'


def test_create_preview_request_omits_null_repeated_fields(test_db_session) -> None:
    payload = _preview_payload()
    analysis_pipeline = payload['analysis_pipeline']
    assert isinstance(analysis_pipeline, dict)
    tabs = analysis_pipeline['tabs']
    assert isinstance(tabs, list)
    tab = tabs[0]
    assert isinstance(tab, dict)
    tab['steps'] = [
        {
            'id': 'dedup-1',
            'type': 'deduplicate',
            'config': {'subset': None, 'keep': 'first'},
            'depends_on': [],
        }
    ]
    payload['target_step_id'] = 'dedup-1'

    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=payload,
    )

    envelope = command_envelope_from_json(request.request_json)

    deduplicate = envelope.command.preview.analysis_pipeline.tabs[0].steps[0].config.deduplicate
    assert list(deduplicate.subset) == []
    assert deduplicate.keep == enums_pb2.DEDUPLICATE_KEEP_FIRST


def test_mark_request_completed_stores_typed_response_envelope(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        response_json={
            'step_id': 'source',
            'columns': ['id'],
            'column_types': {'id': 'Int64'},
            'data': [{'id': 1}],
            'total_rows': 1,
            'page': 1,
            'page_size': 100,
        },
    )

    assert completed.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    assert completed.response_json is not None
    assert completed.response_json['kind'] == 'COMPUTE_REQUEST_KIND_PREVIEW'
    assert completed.response_json['version'] == 1
    assert completed.response_json['correlation_id'] == request.id
    assert completed.response_json['status'] == 'COMPUTE_REQUEST_STATUS_COMPLETED'
    assert 'error_message' not in completed.response_json
    response_envelope = response_envelope_from_json(completed.response_json)
    assert response_envelope.response.WhichOneof('response') == 'preview'
    assert compute_requests_service.response_payload(completed) == {
        'step_id': 'source',
        'columns': ['id'],
        'column_types': {'id': 'Int64'},
        'data': [{'id': 1}],
        'total_rows': 1,
        'page': 1,
        'page_size': 100,
    }
    outbox_event = test_db_session.execute(select(RuntimeOutboxEvent)).scalars().one()
    assert outbox_event.kind == RuntimePayloadKind.COMPUTE_RESPONSE.value
    assert outbox_event.status == RuntimeOutboxStatus.PENDING
    assert outbox_event.payload_json == {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request.id}


def test_row_count_response_preserves_zero_count(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
        request_json=_preview_payload(),
    )

    completed = compute_requests_service.mark_request_completed(test_db_session, request.id, response_json={'step_id': 'filter-1', 'row_count': 0})

    assert compute_requests_service.response_payload(completed) == {'step_id': 'filter-1', 'row_count': 0}


def test_failed_response_preserves_integral_status_code(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )

    failed = compute_requests_service.mark_request_failed(
        test_db_session,
        request.id,
        error_message='Datasource output is not available',
        response_json={
            'error': 'Datasource output is not available',
            'status_code': 409,
            'error_code': 'DATASOURCE_NOT_FOUND',
            'details': {'datasource_id': 'datasource-1'},
        },
    )

    assert compute_requests_service.response_payload(failed) == {
        'error': 'Datasource output is not available',
        'status_code': 409,
        'error_code': 'DATASOURCE_NOT_FOUND',
        'details': {'datasource_id': 'datasource-1'},
    }
    response_envelope = response_envelope_from_json(failed.response_json or {})
    assert response_envelope.response.WhichOneof('response') == 'error'
    assert response_envelope.response.error.error_code == errors_pb2.ERROR_CODE_DATASOURCE_NOT_FOUND


def test_datasource_error_result_shape_uses_typed_compute_error_message(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        request_json={'datasource_id': 'missing'},
    )

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        response_json={'error': 'datasource_not_found', 'message': 'DataSource missing not found'},
    )

    assert compute_requests_service.response_payload(completed) == {
        'error': 'datasource_not_found',
        'message': 'DataSource missing not found',
    }
    response_envelope = response_envelope_from_json(completed.response_json or {})
    assert response_envelope.response.WhichOneof('response') == 'error'
    assert response_envelope.response.error.message == 'DataSource missing not found'


def test_compute_envelope_payload_helpers_reject_deprecated_payload_only_messages() -> None:
    command_envelope = compute_pb2.ComputeCommandEnvelope(
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        version=1,
        idempotency_key='request-1',
        correlation_id='request-1',
        payload=dict_to_struct({'legacy': True}),
    )
    response_envelope = compute_pb2.ComputeResponseEnvelope(
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        version=1,
        correlation_id='request-1',
        status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
        payload=dict_to_struct({'legacy': True}),
    )

    with pytest.raises(ValueError, match='missing typed command'):
        command_payload(command_envelope)
    with pytest.raises(ValueError, match='missing typed response'):
        response_payload(response_envelope)


def test_column_stats_response_preserves_required_zero_defaults(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS,
        request_json={
            'datasource_id': 'datasource-1',
            'column_name': 'city',
            'use_sample': True,
            'sample_size': 1000,
            'datasource_config': {},
        },
    )

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        response_json={
            'column': 'city',
            'dtype': 'String',
            'count': 2,
            'null_count': 0,
            'null_percentage': 0.0,
            'histogram': [{'start': 0.0, 'end': 1.0, 'count': 0}, {'start': 1.0, 'end': 2.0, 'count': 2}],
        },
    )

    assert compute_requests_service.response_payload(completed) == {
        'column': 'city',
        'dtype': 'String',
        'count': 2,
        'null_count': 0,
        'null_percentage': 0.0,
        'histogram': [{'start': 0.0, 'end': 1.0, 'count': 0}, {'start': 1.0, 'end': 2.0, 'count': 2}],
    }


def test_claim_next_request_reclaims_expired_lease(test_db_session) -> None:
    request = compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
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
