from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from backend_core import compute_requests_service
from backend_core.domain.compute_requests.models import (
    command_from_payload,
    datasource_result_from_payload,
    kind_from_proto,
    response_envelope,
    response_payload,
)
from backend_core.domain.runtime.events import RuntimePayloadKind
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.transitions import TransitionOutcome
from dataforge_protocol import compute_pb2, datasource_pb2, enums_pb2, errors_pb2
from modules.analysis.step_schemas import normalize_step_config_for_protocol


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


def _create_request(
    test_db_session,
    *,
    namespace: str,
    kind: enums_pb2.ComputeRequestKind,
    request_json: dict[str, object],
    commit: bool = True,
) -> ComputeRequest:
    pipeline = request_json.get('analysis_pipeline')
    if isinstance(pipeline, dict):
        for tab in pipeline.get('tabs', []):
            if not isinstance(tab, dict):
                continue
            for step in tab.get('steps', []):
                if not isinstance(step, dict):
                    continue
                step_type = step.get('type')
                config = step.get('config')
                if isinstance(step_type, str) and isinstance(config, dict):
                    step['config'] = normalize_step_config_for_protocol(step_type, config)
    command = command_from_payload(kind, request_json)
    if not commit:
        return compute_requests_service.stage_request(
            test_db_session,
            namespace=namespace,
            kind=kind,
            command=command,
        )
    return compute_requests_service.create_request(
        test_db_session,
        namespace=namespace,
        kind=kind,
        command=command,
    )


def _stored_command(request: ComputeRequest) -> compute_pb2.ComputeCommandEnvelope:
    return compute_pb2.ComputeCommandEnvelope.FromString(request.command_envelope)


def _stored_response(request: ComputeRequest) -> compute_pb2.ComputeResponseEnvelope:
    if request.response_envelope is None:
        raise AssertionError('expected a stored response envelope')
    return compute_pb2.ComputeResponseEnvelope.FromString(request.response_envelope)


def _response(
    request: ComputeRequest,
    payload: dict[str, object],
    *,
    status: enums_pb2.ComputeRequestStatus = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
    error_message: str | None = None,
) -> compute_pb2.ComputeResponseEnvelope:
    return response_envelope(kind=kind_from_proto(request.kind), request_id=request.id, status=status, payload=payload, error_message=error_message)


def _claim_identity(test_db_session, request: ComputeRequest) -> tuple[str, str, int]:
    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-test')
    assert claimed is not None
    assert claimed.id == request.id
    assert claimed.lease_owner is not None
    assert claimed.claim_token is not None
    return claimed.lease_owner, claimed.claim_token, claimed.lease_generation


def test_preview_command_converts_all_pipeline_output_enums() -> None:
    payload = _preview_payload()
    pipeline = cast(dict[str, object], payload['analysis_pipeline'])
    tabs = cast(list[dict[str, object]], pipeline['tabs'])
    output = cast(dict[str, object], tabs[0]['output'])
    output.update(
        {
            'datasource_type': 'iceberg',
            'build_mode': 'full',
            'notification': {'method': 'email'},
        }
    )

    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, payload).preview

    protocol_output = command.analysis_pipeline.tabs[0].output
    assert protocol_output.datasource_type == enums_pb2.DATA_SOURCE_TYPE_ICEBERG
    assert protocol_output.build_mode == enums_pb2.BUILD_MODE_FULL
    assert protocol_output.notification.method == enums_pb2.NOTIFICATION_METHOD_EMAIL


def test_claim_next_request_prioritizes_user_create_requests_over_previews(test_db_session) -> None:
    create_request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload', 'file_path': 's3://data/upload.csv', 'file_type': 'csv', 'options': {}},
    )
    preview = _create_request(
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
    background = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        request_json={'datasource_id': 'background'},
    )
    create_request = _create_request(
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


def test_mark_request_failed_after_transaction_owner_rolls_back(test_db_session) -> None:
    request = _create_request(test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, request_json=_preview_payload())
    request_id = request.id
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)

    duplicate = (
        ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
        .insert()
        .values(
            id=request_id,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
            command_envelope=b'duplicate',
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        test_db_session.execute(duplicate)
        test_db_session.commit()
    test_db_session.rollback()

    failed = compute_requests_service.mark_request_failed(
        test_db_session,
        request_id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        error_message='boom',
        response_envelope=_response(
            request,
            {'error': 'boom', 'status_code': 500},
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            error_message='boom',
        ),
    )
    assert failed is not None

    assert failed.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert failed.error_message == 'boom'
    stored_response = _stored_response(failed)
    assert stored_response.kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW
    assert stored_response.version == 1
    assert stored_response.correlation_id == request_id
    assert stored_response.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert stored_response.error_message == 'boom'
    assert stored_response.response.WhichOneof('response') == 'error'
    assert compute_requests_service.response_payload(failed) == {'error': 'boom', 'status_code': 500}
    outbox_event = test_db_session.execute(select(RuntimeOutboxEvent)).scalars().one()
    assert outbox_event.kind == RuntimePayloadKind.COMPUTE_RESPONSE.value
    assert outbox_event.status == RuntimeOutboxStatus.PENDING
    assert outbox_event.payload_json == {'kind': RuntimePayloadKind.COMPUTE_RESPONSE.value, 'request_id': request_id}
    assert failed.completed_at is not None


def test_create_request_stores_typed_command_envelope(test_db_session) -> None:
    request = _create_request(
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

    envelope = _stored_command(request)
    assert envelope.kind == enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE
    assert envelope.version == 1
    assert envelope.idempotency_key == request.id
    assert envelope.correlation_id == request.id
    assert envelope.command.WhichOneof('command') == 'spawn_engine'
    assert envelope.command.spawn_engine.engine_identity.scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert envelope.command.spawn_engine.engine_identity.resource_id == 'analysis-1'
    assert envelope.command.spawn_engine.resource_config.max_memory_mb == 512


def test_create_preview_request_stores_typed_command_envelope(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )

    envelope = _stored_command(request)

    assert envelope.command.WhichOneof('command') == 'preview'
    assert envelope.command.preview.target_step_id == 'source'
    assert envelope.command.preview.analysis_pipeline.analysis_id == 'analysis-1'
    assert envelope.command.preview.analysis_pipeline.tabs[0].datasource.source_type == enums_pb2.DATA_SOURCE_TYPE_FILE


def test_datasource_response_uses_typed_schema_info_but_preserves_schema_cache_payload() -> None:
    payload: dict[str, object] = {
        'id': 'datasource-1',
        'name': 'Datasource',
        'source_type': 'file',
        'config': {'file_path': 's3://bucket/data.csv'},
        'schema_cache': {
            'columns': [{'name': 'id', 'dtype': 'Int64', 'nullable': False}],
            'row_count': 1,
        },
        'created_by': 'import',
        'is_hidden': False,
        'created_at': '2026-06-28T00:00:00Z',
    }

    result = datasource_result_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE, payload)

    assert result.WhichOneof('result') == 'datasource'
    assert isinstance(result.datasource.schema_info, datasource_pb2.SchemaInfo)
    assert result.datasource.schema_info.columns[0].name == 'id'
    envelope = compute_pb2.ComputeResponseEnvelope(
        kind=enums_pb2.COMPUTE_REQUEST_KIND_INGEST_DATASOURCE,
        version=1,
        correlation_id='request-1',
        status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
        response=compute_pb2.ComputeResponse(datasource=result),
    )
    decoded = response_payload(envelope)
    assert decoded['schema_cache'] == payload['schema_cache']


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

    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=payload,
    )

    envelope = _stored_command(request)

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

    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=payload,
    )

    envelope = _stored_command(request)
    step = envelope.command.preview.analysis_pipeline.tabs[0].steps[0]

    assert step.step_type == enums_pb2.STEP_TYPE_PLOT_SCATTER
    assert step.config.WhichOneof('config') == 'chart'


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

    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=payload,
    )

    envelope = _stored_command(request)

    deduplicate = envelope.command.preview.analysis_pipeline.tabs[0].steps[0].config.deduplicate
    assert list(deduplicate.subset) == []
    assert deduplicate.keep == enums_pb2.DEDUPLICATE_KEEP_FIRST


def test_mark_request_completed_stores_typed_response_envelope(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(
            request,
            {
                'step_id': 'source',
                'columns': ['id'],
                'column_types': {'id': 'Int64'},
                'data': [{'id': 1}],
                'total_rows': 1,
                'page': 1,
                'page_size': 100,
            },
        ),
    )
    assert completed is not None

    assert completed.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    stored_response = _stored_response(completed)
    assert stored_response.kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW
    assert stored_response.version == 1
    assert stored_response.correlation_id == request.id
    assert stored_response.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    assert not stored_response.HasField('error_message')
    assert stored_response.response.WhichOneof('response') == 'preview'
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
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(request, {'step_id': 'filter-1', 'row_count': 0}),
    )
    assert completed is not None

    assert compute_requests_service.response_payload(completed) == {'step_id': 'filter-1', 'row_count': 0}


def test_failed_response_preserves_integral_status_code(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)

    failed = compute_requests_service.mark_request_failed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        error_message='Datasource output is not available',
        response_envelope=_response(
            request,
            {
                'error': 'Datasource output is not available',
                'status_code': 409,
                'error_code': 'DATASOURCE_NOT_FOUND',
                'details': {'datasource_id': 'datasource-1'},
            },
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            error_message='Datasource output is not available',
        ),
    )
    assert failed is not None

    assert compute_requests_service.response_payload(failed) == {
        'error': 'Datasource output is not available',
        'status_code': 409,
        'error_code': 'DATASOURCE_NOT_FOUND',
        'details': {'datasource_id': 'datasource-1'},
    }
    stored_response = _stored_response(failed)
    assert stored_response.response.WhichOneof('response') == 'error'
    assert stored_response.response.error.error_code == errors_pb2.ERROR_CODE_DATASOURCE_NOT_FOUND


def test_datasource_error_result_shape_uses_typed_compute_error_message(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        request_json={'datasource_id': 'missing'},
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(request, {'error': 'datasource_not_found', 'message': 'DataSource missing not found'}),
    )
    assert completed is not None

    assert compute_requests_service.response_payload(completed) == {
        'error': 'datasource_not_found',
        'message': 'DataSource missing not found',
    }
    stored_response = _stored_response(completed)
    assert stored_response.response.WhichOneof('response') == 'error'
    assert stored_response.response.error.message == 'DataSource missing not found'


def test_compute_envelope_payload_helpers_reject_missing_typed_messages() -> None:
    response_envelope = compute_pb2.ComputeResponseEnvelope(
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        version=1,
        correlation_id='request-1',
        status=enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED,
    )

    with pytest.raises(ValueError, match='missing typed response'):
        response_payload(response_envelope)


def test_column_stats_response_preserves_required_zero_defaults(test_db_session) -> None:
    request = _create_request(
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
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(
            request,
            {
                'column': 'city',
                'dtype': 'String',
                'count': 2,
                'null_count': 0,
                'null_percentage': 0.0,
                'histogram': [{'start': 0.0, 'end': 1.0, 'count': 0}, {'start': 1.0, 'end': 2.0, 'count': 2}],
            },
        ),
    )
    assert completed is not None

    assert compute_requests_service.response_payload(completed) == {
        'column': 'city',
        'dtype': 'String',
        'count': 2,
        'null_count': 0,
        'null_percentage': 0.0,
        'histogram': [{'start': 0.0, 'end': 1.0, 'count': 0}, {'start': 1.0, 'end': 2.0, 'count': 2}],
    }


def test_reclaimed_request_rejects_stale_completion(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    first_claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')
    assert first_claim is not None
    assert first_claim.claim_token is not None
    first_token = first_claim.claim_token
    first_generation = first_claim.lease_generation
    first_claim.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(first_claim)
    test_db_session.commit()

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2')

    assert claimed is not None
    assert claimed.id == request.id
    assert claimed.lease_owner == 'worker-2'
    assert claimed.claim_token is not None
    assert claimed.claim_token != first_token
    assert claimed.lease_generation == first_generation + 1
    assert claimed.attempts == 2
    assert claimed.lease_expires_at is not None

    stale_completion = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id='worker-1',
        claim_token=first_token,
        lease_generation=first_generation,
        response_envelope=_response(
            request,
            {'step_id': 'source', 'columns': [], 'column_types': {}, 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
        ),
    )
    assert stale_completion is None

    renewed = compute_requests_service.renew_request_lease(
        test_db_session,
        request.id,
        worker_id='worker-2',
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
    )
    assert renewed.outcome is TransitionOutcome.APPLIED
    assert renewed.value is not None


def test_expired_request_is_failed_after_attempt_exhaustion(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    request.max_attempts = 1
    test_db_session.add(request)
    test_db_session.commit()
    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')
    assert claimed is not None
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(claimed)
    test_db_session.commit()

    assert compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2') is None

    test_db_session.refresh(claimed)
    assert claimed.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert claimed.error_message == 'Compute request exhausted 1 execution attempts'
    assert claimed.response_envelope is not None
    assert response_payload(_stored_response(claimed))['error'] == 'Compute request exhausted 1 execution attempts'
