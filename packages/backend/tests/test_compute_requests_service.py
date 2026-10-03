from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend_core import compute_requests_service
from backend_core.claiming import CLAIM_DELIVERY_LEASE_SECONDS
from backend_core.config import settings
from backend_core.domain.compute_requests.models import (
    command_from_payload,
    datasource_result_from_payload,
    kind_from_proto,
    response_envelope,
    response_payload,
)
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.compute_requests.models import ComputeRequest, ComputeRequestFlight
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.engine_runs.models import EngineRun
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent
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


def _analysis_read_command(kind: enums_pb2.ComputeRequestKind, *, analysis_id: str = 'analysis-1', target_step_id: str = 'source'):
    preview_payload = _preview_payload()
    return command_from_payload(
        kind,
        {
            'analysis_id': analysis_id,
            'target_step_id': target_step_id,
            'tab_id': 'tab-1',
            'analysis_pipeline': preview_payload['analysis_pipeline'],
        },
    )


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


def _create_preview_engine_run(session) -> EngineRun:
    run = EngineRun(
        id=str(uuid4()),
        namespace='default',
        analysis_id='analysis-1',
        datasource_id='datasource-1',
        kind=EngineRunKind.PREVIEW.value,
        status=EngineRunStatus.RUNNING.value,
        request_json={},
        result_json={},
        created_at=datetime.now(UTC),
        step_timings={},
        progress=0.0,
    )
    session.add(run)
    session.commit()
    return run


def test_stage_shared_flight_request_reuses_one_durable_active_flight(test_db_session, monkeypatch) -> None:
    from backend_core import runtime_work_service

    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())
    validations: list[str] = []
    wake_writes: list[tuple[str, runtime_work_service.RuntimeWorkKind]] = []
    monkeypatch.setattr(
        runtime_work_service,
        'append_wake',
        lambda _session, *, namespace, kind: wake_writes.append((namespace, kind)),
    )

    leader, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
        validate=lambda: validations.append('leader'),
    )
    assert created is True
    assert wake_writes == [('default', runtime_work_service.RuntimeWorkKind.COMPUTE)]
    test_db_session.commit()
    monkeypatch.setattr(compute_requests_service, '_try_lock_flight', lambda *_args: pytest.fail('active followers must bypass the flight advisory lock'))

    follower, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
        validate=lambda: validations.append('follower'),
    )
    assert created is False
    assert follower.id == leader.id
    assert validations == ['leader', 'follower']
    assert wake_writes == [('default', runtime_work_service.RuntimeWorkKind.COMPUTE)]
    assert len(test_db_session.execute(select(ComputeRequest)).scalars().all()) == 1


def test_stage_shared_flight_request_reuses_completed_durable_response(test_db_session, monkeypatch) -> None:
    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())
    leader, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
    )
    assert created is True
    test_db_session.commit()

    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, leader)
    response = _response(
        leader,
        {'step_id': 'source', 'columns': [], 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
    )
    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        leader.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=response,
    )
    assert completed is not None
    monkeypatch.setattr(compute_requests_service, '_try_lock_flight', lambda *_args: pytest.fail('cached followers must bypass the flight advisory lock'))

    cached, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
    )

    assert created is False
    assert cached.id == leader.id
    assert cached.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    flight = test_db_session.exec(select(ComputeRequestFlight).where(ComputeRequestFlight.request_id == leader.id)).one()
    assert (flight.expires_at - completed.completed_at).total_seconds() == 300


def test_list_terminal_requests_returns_batched_detached_response_fields(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)
    compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(
            request,
            {'step_id': 'source', 'columns': [], 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
        ),
    )

    terminal = compute_requests_service.list_terminal_requests(test_db_session, [request.id, 'missing'])

    assert len(terminal) == 1
    assert terminal[0].id == request.id
    assert terminal[0].kind == int(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW)
    assert terminal[0].status == int(enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED)
    assert compute_requests_service.response_payload(terminal[0])['step_id'] == 'source'
    assert not hasattr(terminal[0], 'command_envelope')


def test_completed_request_retry_is_idempotent_and_rejects_a_different_result(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)
    response = _response(
        request,
        {'step_id': 'source', 'columns': [], 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
    )
    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=response,
    )
    assert completed is not None

    retried = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=response,
    )
    conflicting = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(
            request,
            {'step_id': 'source', 'columns': [], 'data': [{'unexpected': True}], 'total_rows': 1, 'page': 1, 'page_size': 100},
        ),
    )

    assert retried is not None
    assert retried.completed_at == completed.completed_at
    assert retried.response_envelope == completed.response_envelope
    assert conflicting is None


def test_failed_request_retry_is_idempotent(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)
    response = _response(
        request,
        {'error': 'preview failed', 'status_code': 500},
        status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
        error_message='preview failed',
    )
    failed = compute_requests_service.mark_request_failed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        error_message='preview failed',
        response_envelope=response,
    )
    assert failed is not None

    retried = compute_requests_service.mark_request_failed(
        test_db_session,
        request.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        error_message='preview failed',
        response_envelope=response,
    )

    assert retried is not None
    assert retried.completed_at == failed.completed_at
    assert retried.response_envelope == failed.response_envelope


def test_completed_preview_cache_is_invalidated_by_datasource_revision(test_db_session) -> None:
    test_db_session.add(
        DataSource(
            id='datasource-1',
            name='source',
            source_type='file',
            config={},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())
    leader, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
    )
    assert created is True
    test_db_session.commit()

    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, leader)
    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        leader.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(
            leader,
            {'step_id': 'source', 'columns': [], 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
        ),
    )
    assert completed is not None

    datasource = test_db_session.get(DataSource, 'datasource-1')
    assert datasource is not None
    datasource.revision += 1
    test_db_session.add(datasource)
    test_db_session.commit()

    refreshed, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
    )
    assert created is True
    assert refreshed.id != leader.id


def test_stage_shared_flight_request_keeps_distinct_commands_independent(test_db_session) -> None:
    first_command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())
    second_payload = _preview_payload()
    second_payload['row_limit'] = 101
    second_command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, second_payload)

    first, first_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=first_command,
    )
    test_db_session.commit()
    second, second_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=second_command,
    )
    test_db_session.commit()

    assert first_created is True
    assert second_created is True
    assert first.id != second.id


def test_stage_shared_flight_request_is_scoped_by_namespace(test_db_session) -> None:
    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())

    default_request, default_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
    )
    test_db_session.commit()
    other_request, other_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='other-tenant',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=command,
    )

    assert default_created is True
    assert other_created is True
    assert default_request.id != other_request.id
    assert default_request.namespace == 'default'
    assert other_request.namespace == 'other-tenant'


def test_stage_shared_flight_request_preserves_full_iceberg_command_identity(test_db_session) -> None:
    first_command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())
    datasource_config = first_command.preview.analysis_pipeline.tabs[0].datasource.config
    datasource_config.fields['current_snapshot_id'].string_value = 'snapshot-1'
    datasource_config.fields['metadata_path'].string_value = 's3://bucket/claim-a/metadata.json'

    second_command = compute_pb2.ComputeCommand()
    second_command.CopyFrom(first_command)
    second_command.preview.analysis_pipeline.tabs[0].datasource.config.fields['metadata_path'].string_value = 's3://bucket/claim-b/metadata.json'

    first, first_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=first_command,
    )
    test_db_session.commit()
    second, second_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=second_command,
    )

    assert first_created is True
    assert second_created is True
    assert first.id != second.id


def test_stage_shared_flight_request_keys_the_exact_analysis_rid(test_db_session) -> None:
    first_command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())
    second_command = compute_pb2.ComputeCommand()
    second_command.CopyFrom(first_command)
    second_command.preview.analysis_id = 'analysis-other-rid'
    second_command.preview.analysis_pipeline.analysis_id = 'analysis-other-rid'

    first, first_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=first_command,
    )
    test_db_session.commit()
    second, second_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=second_command,
    )

    assert first_created is True
    assert second_created is True
    assert first.id != second.id


@pytest.mark.parametrize(
    'kind',
    [enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA, enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT],
)
def test_stage_shared_flight_request_coalesces_analysis_reads_by_rid_and_command(test_db_session, kind) -> None:
    command = _analysis_read_command(kind)
    leader, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=kind,
        command=command,
    )
    assert created is True
    test_db_session.commit()

    follower, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=kind,
        command=command,
    )
    assert created is False
    assert follower.id == leader.id

    other_analysis = _analysis_read_command(kind, analysis_id='analysis-other-rid')
    other_transform = _analysis_read_command(kind, target_step_id='another-step')
    other_analysis_request, other_analysis_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=kind,
        command=other_analysis,
    )
    test_db_session.commit()
    other_transform_request, other_transform_created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=kind,
        command=other_transform,
    )

    assert other_analysis_created is True
    assert other_transform_created is True
    assert other_analysis_request.id != leader.id
    assert other_transform_request.id != leader.id


def test_stage_shared_flight_rejects_mismatched_command_kind(test_db_session) -> None:
    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, _preview_payload())

    with pytest.raises(ValueError, match='requires a schema command'):
        compute_requests_service.stage_shared_flight_request(
            test_db_session,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
            command=command,
        )


def test_stage_datasource_schema_reuses_one_durable_flight_and_cache(test_db_session) -> None:
    command = command_from_payload(
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        {'datasource_id': 'datasource-1', 'sheet_name': None, 'refresh': False},
    )

    leader, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
    )
    assert created is True
    test_db_session.commit()

    follower, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
    )
    assert created is False
    assert follower.id == leader.id

    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, leader)
    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        leader.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(leader, {'columns': [], 'row_count': 0}),
    )
    assert completed is not None

    cached, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
    )
    assert created is False
    assert cached.id == leader.id


def test_refresh_datasource_schema_coalesces_active_work_but_does_not_cache_completion(test_db_session) -> None:
    command = command_from_payload(
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        {'datasource_id': 'datasource-refresh', 'sheet_name': None, 'refresh': True},
    )

    leader, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
    )
    assert created is True
    test_db_session.commit()

    follower, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
    )
    assert created is False
    assert follower.id == leader.id

    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, leader)
    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        leader.id,
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(leader, {'columns': [], 'row_count': 0}),
    )
    assert completed is not None

    refreshed, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA,
        command=command,
    )

    assert created is True
    assert refreshed.id != leader.id


def test_has_active_request_for_datasource_tracks_queued_work(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )

    assert compute_requests_service.has_active_request_for_datasource(test_db_session, 'datasource-1') is True
    assert compute_requests_service.has_active_request_for_datasource(test_db_session, 'datasource-2') is False

    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    test_db_session.add(request)
    test_db_session.commit()

    assert compute_requests_service.has_active_request_for_datasource(test_db_session, 'datasource-1') is False


def test_request_dependency_index_includes_join_and_union_sources() -> None:
    payload = _preview_payload()
    pipeline = payload['analysis_pipeline']
    assert isinstance(pipeline, dict)
    tabs = pipeline['tabs']
    assert isinstance(tabs, list)
    tab = tabs[0]
    assert isinstance(tab, dict)
    tab['steps'] = [
        {'id': 'join-1', 'type': 'join', 'config': {'right_source': 'datasource-join'}},
        {'id': 'union-1', 'type': 'union_by_name', 'config': {'sources': ['datasource-union-a', 'datasource-union-b']}},
    ]
    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW, payload)

    assert compute_requests_service._datasource_ids_for_command(command) == {
        'datasource-1',
        'datasource-join',
        'datasource-union-a',
        'datasource-union-b',
    }


def test_cancel_queued_request_retires_abandoned_work(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )

    cancelled = compute_requests_service.cancel_queued_request(
        test_db_session,
        request.id,
        reason='client disconnected',
    )

    assert cancelled is not None
    assert cancelled.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert cancelled.error_message == 'client disconnected'
    assert compute_requests_service.response_payload(cancelled) == {'error': 'client disconnected'}
    assert compute_requests_service.claim_next_request(test_db_session, worker_id='worker-test') is None


def test_empty_claim_does_not_refresh_namespace_work_marker(test_db_session, monkeypatch) -> None:
    def unexpected_refresh(*_args, **_kwargs) -> None:
        raise AssertionError('empty claims must not scan and refresh the durable namespace marker')

    monkeypatch.setattr(compute_requests_service.runtime_work_service, 'refresh_pending_work', unexpected_refresh)

    assert compute_requests_service.claim_next_request(test_db_session, worker_id='worker-test') is None


def test_cancel_queued_request_does_not_take_over_running_work(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    compute_requests_service.claim_next_request(test_db_session, worker_id='worker-test')

    cancelled = compute_requests_service.cancel_queued_request(
        test_db_session,
        request.id,
        reason='client disconnected',
    )

    assert cancelled is None
    active = compute_requests_service.get_request(test_db_session, request.id)
    assert active is not None
    assert active.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING


@pytest.mark.parametrize(
    'kind',
    [
        enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        enums_pb2.COMPUTE_REQUEST_KIND_ROW_COUNT,
    ],
)
def test_cancel_disconnected_request_preserves_running_shared_analysis_reads(test_db_session, kind) -> None:
    command = command_from_payload(kind, _preview_payload()) if kind == enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW else _analysis_read_command(kind)
    request, created = compute_requests_service.stage_shared_flight_request(
        test_db_session,
        namespace='default',
        kind=kind,
        command=command,
    )
    assert created is True
    test_db_session.commit()
    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-test')
    assert claimed is not None

    cancelled = compute_requests_service.cancel_disconnected_request(
        test_db_session,
        request.id,
        reason='client disconnected',
    )

    assert cancelled is None
    active = compute_requests_service.get_request(test_db_session, request.id)
    assert active is not None
    assert active.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert active.lease_owner == 'worker-test'
    assert active.claim_token == claimed.claim_token


def test_cancel_active_requests_for_engine_retires_only_matching_work(test_db_session) -> None:
    matching_payload = _preview_payload()
    other_payload = deepcopy(matching_payload)
    other_payload['analysis_id'] = 'analysis-2'
    other_pipeline = other_payload['analysis_pipeline']
    assert isinstance(other_pipeline, dict)
    other_pipeline['analysis_id'] = 'analysis-2'

    matching = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=matching_payload,
    )
    other = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=other_payload,
    )

    cancelled = compute_requests_service.cancel_active_requests_for_engine(
        test_db_session,
        namespace='default',
        identity=compute_pb2.EngineIdentity(
            scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
            reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
            analysis_id='analysis-1',
            resource_id='analysis-1',
        ),
        reason='analysis was deleted',
    )

    assert cancelled == 1
    assert matching.engine_scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert matching.engine_reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert matching.engine_resource_id == 'analysis-1'
    assert other.engine_resource_id == 'analysis-2'
    test_db_session.refresh(matching)
    test_db_session.refresh(other)
    assert matching.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert compute_requests_service.response_payload(matching) == {'error': 'analysis was deleted'}
    assert other.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-test')
    assert claimed is not None
    assert claimed.id == other.id


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


def test_claim_next_request_prioritizes_interactive_preview_over_user_create(test_db_session) -> None:
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
    assert claimed.id == preview.id
    assert claimed.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert claimed.lease_expires_at is not None
    assert claimed.claimed_at is not None
    assert abs((claimed.lease_expires_at - claimed.claimed_at).total_seconds() - CLAIM_DELIVERY_LEASE_SECONDS) < 0.01

    remaining = compute_requests_service.get_request(test_db_session, create_request.id)
    assert remaining is not None
    assert remaining.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


def test_claim_next_request_serializes_exact_engine_identity_and_keeps_other_ids_moving(test_db_session) -> None:
    leader_payload = _preview_payload()
    follower_payload = deepcopy(leader_payload)
    follower_payload['row_limit'] = 101
    other_payload = deepcopy(leader_payload)
    other_payload['analysis_id'] = 'analysis-2'
    cast(dict[str, object], other_payload['analysis_pipeline'])['analysis_id'] = 'analysis-2'

    leader = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=leader_payload,
    )
    follower = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=follower_payload,
    )
    other = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=other_payload,
    )
    created = datetime.now(UTC)
    leader.created_at = created - timedelta(seconds=3)
    follower.created_at = created - timedelta(seconds=2)
    other.created_at = created - timedelta(seconds=1)
    test_db_session.add_all([leader, follower, other])
    test_db_session.commit()

    first_claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')
    second_claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2')

    assert first_claim is not None and first_claim.id == leader.id
    assert second_claim is not None and second_claim.id == other.id
    test_db_session.refresh(follower)
    assert follower.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED

    leader.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    leader.lease_owner = None
    leader.claim_token = None
    leader.lease_expires_at = None
    test_db_session.add(leader)
    test_db_session.commit()

    follower_claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-3')
    assert follower_claim is not None and follower_claim.id == follower.id


def test_claim_next_request_skips_busy_engine_identity_for_claim_call(test_db_session, monkeypatch) -> None:
    first_payload = _preview_payload()
    follower_payload = deepcopy(first_payload)
    follower_payload['row_limit'] = 101
    other_payload = deepcopy(first_payload)
    other_payload['analysis_id'] = 'analysis-2'
    cast(dict[str, object], other_payload['analysis_pipeline'])['analysis_id'] = 'analysis-2'

    first = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=first_payload,
    )
    follower = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=follower_payload,
    )
    other = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=other_payload,
    )
    created = datetime.now(UTC)
    first.created_at = created - timedelta(seconds=3)
    follower.created_at = created - timedelta(seconds=2)
    other.created_at = created - timedelta(seconds=1)
    test_db_session.add_all([first, follower, other])
    test_db_session.commit()

    lock_attempts: list[str] = []

    def try_engine_claim_lock(_session, request: ComputeRequest) -> bool:
        lock_attempts.append(request.engine_resource_id or '')
        return request.engine_resource_id != 'analysis-1'

    monkeypatch.setattr(compute_requests_service, '_lock_engine_claim', try_engine_claim_lock)

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is not None and claimed.id == other.id
    assert lock_attempts == ['analysis-1', 'analysis-2']
    for request in (first, follower, other):
        test_db_session.refresh(request)
    assert first.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
    assert follower.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
    assert other.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING


def test_claim_next_request_busy_engine_identity_does_not_filter_non_engine_work(test_db_session, monkeypatch) -> None:
    busy_request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    now = datetime.now(UTC)
    non_engine_request = ComputeRequest(
        id='non-engine-while-rid-busy',
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_EXPORT,
        status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        command_envelope=b'{}',
        attempts=0,
        max_attempts=3,
        created_at=now + timedelta(seconds=1),
        updated_at=now,
    )
    busy_request.created_at = now
    test_db_session.add_all([busy_request, non_engine_request])
    test_db_session.commit()
    lock_attempts: list[str | None] = []

    def try_engine_claim_lock(_session, request: ComputeRequest) -> bool:
        lock_attempts.append(request.engine_resource_id)
        return request.engine_resource_id is None

    monkeypatch.setattr(compute_requests_service, '_lock_engine_claim', try_engine_claim_lock)

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is not None and claimed.id == non_engine_request.id
    assert lock_attempts == [busy_request.engine_resource_id, None]
    test_db_session.refresh(busy_request)
    assert busy_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
    assert claimed.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING


def test_claim_next_request_returns_none_when_all_remaining_engine_identities_are_busy(test_db_session, monkeypatch) -> None:
    first = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    test_db_session.commit()
    lock_attempts: list[str] = []

    def try_engine_claim_lock(_session, request: ComputeRequest) -> bool:
        lock_attempts.append(request.engine_resource_id or '')
        return False

    monkeypatch.setattr(compute_requests_service, '_lock_engine_claim', try_engine_claim_lock)

    claimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')

    assert claimed is None
    assert lock_attempts == [first.engine_resource_id]
    test_db_session.refresh(first)
    assert first.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


def test_expired_engine_request_is_reclaimed_before_its_follower(test_db_session) -> None:
    leader_payload = _preview_payload()
    follower_payload = deepcopy(leader_payload)
    follower_payload['row_limit'] = 101
    leader = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=leader_payload,
    )
    follower = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=follower_payload,
    )
    leader.created_at = datetime.now(UTC) - timedelta(seconds=2)
    test_db_session.add(leader)
    test_db_session.commit()

    first_claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')
    assert first_claim is not None and first_claim.id == leader.id
    first_generation = first_claim.lease_generation
    first_claim.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(first_claim)
    test_db_session.commit()

    reclaimed = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2')

    assert reclaimed is not None and reclaimed.id == leader.id
    assert reclaimed.lease_generation == first_generation + 1
    test_db_session.refresh(follower)
    assert follower.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


def test_staged_schema_request_uses_pipeline_analysis_rid_for_engine_ownership(test_db_session) -> None:
    pipeline = deepcopy(cast(dict[str, object], _preview_payload()['analysis_pipeline']))
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SCHEMA,
        request_json={'target_step_id': 'source', 'tab_id': 'tab-1', 'analysis_pipeline': pipeline},
    )

    assert request.engine_scope == enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE
    assert request.engine_reuse_policy == enums_pb2.ENGINE_REUSE_POLICY_SHARED
    assert request.engine_resource_id == 'analysis-1'


def test_claim_next_request_filters_engine_work_for_non_engine_lane(test_db_session) -> None:
    preview = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    create_request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        request_json={'name': 'upload', 'file_path': 's3://data/upload.csv', 'file_type': 'csv', 'options': {}},
    )

    claimed = compute_requests_service.claim_next_request(
        test_db_session,
        worker_id='non-engine-worker',
        allowed_kinds={enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE},
    )

    assert claimed is not None
    assert claimed.id == create_request.id
    test_db_session.refresh(preview)
    assert preview.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED


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
    assert test_db_session.execute(select(RuntimeOutboxEvent)).scalars().all() == []
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


def test_reclaim_during_completion_preparation_rolls_back_engine_run_finalization(test_db_session, monkeypatch) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)
    request_id = request.id

    engine_run = _create_preview_engine_run(test_db_session)
    stage_started = Event()
    resume_stage = Event()
    finalization_time = datetime.now(UTC)
    finalization = compute_requests_service.EngineRunFinalization(
        run_id=engine_run.id,
        fields={
            'status': EngineRunStatus.SUCCESS.value,
            'completed_at': finalization_time,
            'duration_ms': 42,
        },
        merge_result_json=False,
    )
    original_stage_finalization = compute_requests_service._stage_engine_run_finalization

    def pause_engine_run_finalization(session, claim, staged_finalization, *, expected_status) -> None:
        assert expected_status == EngineRunStatus.SUCCESS
        assert 'command_envelope' in inspect(claim).unloaded
        original_stage_finalization(
            session,
            claim,
            staged_finalization,
            expected_status=expected_status,
        )
        stage_started.set()
        if not resume_stage.wait(timeout=5):
            raise TimeoutError('test did not release engine-run finalization')

    monkeypatch.setattr(compute_requests_service, '_stage_engine_run_finalization', pause_engine_run_finalization)
    response = _response(
        request,
        {'step_id': 'source', 'columns': [], 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
    )
    engine = test_db_session.get_bind()

    def complete_request():
        token = set_namespace_context('default')
        try:
            with Session(engine) as session:
                return compute_requests_service.mark_request_completed(
                    session,
                    request_id,
                    worker_id=worker_id,
                    claim_token=claim_token,
                    lease_generation=lease_generation,
                    response_envelope=response,
                    engine_run_finalization=finalization,
                )
        finally:
            reset_namespace(token)

    def expire_and_reclaim():
        token = set_namespace_context('default')
        try:
            with Session(engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '500ms'"))
                expired = session.execute(
                    update(ComputeRequest).where(ComputeRequest.id == request_id).values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
                )
                assert expired.rowcount == 1
                session.commit()
                reclaimed = compute_requests_service.claim_next_request(session, worker_id='worker-reclaimed')
                assert reclaimed is not None
                return reclaimed
        finally:
            reset_namespace(token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion = executor.submit(complete_request)
        try:
            assert stage_started.wait(timeout=3)
            # The completion has staged an EngineRun update but must not yet
            # own the ComputeRequest row. A new worker can expire and reclaim
            # the lease while that work is paused.
            reclaimed = executor.submit(expire_and_reclaim).result(timeout=3)
            assert reclaimed.id == request_id
            assert reclaimed.lease_owner == 'worker-reclaimed'
        finally:
            resume_stage.set()
        assert completion.result(timeout=5) is None

    test_db_session.expire_all()
    persisted_run = test_db_session.get(EngineRun, engine_run.id)
    assert persisted_run is not None
    assert persisted_run.status == EngineRunStatus.RUNNING.value
    persisted_request = compute_requests_service.get_request(test_db_session, request_id)
    assert persisted_request is not None
    assert persisted_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert persisted_request.lease_owner == 'worker-reclaimed'


def test_preview_completion_commits_request_and_engine_run_together(test_db_session, monkeypatch) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    claim = compute_requests_service.claim_next_request(test_db_session, worker_id='worker-1')
    assert claim is not None and claim.claim_token is not None
    engine_run = _create_preview_engine_run(test_db_session)

    def fail_response_serialization(_run) -> None:
        raise AssertionError('compute completion must not serialize an unused engine-run response')

    monkeypatch.setattr(compute_requests_service.engine_runs_service, '_serialize_run', fail_response_serialization)

    completed = compute_requests_service.mark_request_completed(
        test_db_session,
        request.id,
        worker_id='worker-1',
        claim_token=claim.claim_token,
        lease_generation=claim.lease_generation,
        response_envelope=_response(
            request,
            {'step_id': 'source', 'columns': [], 'column_types': {}, 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
        ),
        engine_run_finalization=compute_requests_service.EngineRunFinalization(
            run_id=engine_run.id,
            fields={
                'status': EngineRunStatus.SUCCESS.value,
                'result_json': {'results': [{'status': 'success'}]},
                'completed_at': datetime.now(UTC),
                'progress': 1.0,
            },
        ),
    )

    assert completed is not None
    test_db_session.expire_all()
    stored_request = test_db_session.get(ComputeRequest, request.id)
    stored_run = test_db_session.get(EngineRun, engine_run.id)
    assert stored_request is not None
    assert stored_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    assert stored_run is not None
    assert stored_run.status == EngineRunStatus.SUCCESS.value
    assert stored_run.result_json == {'results': [{'status': 'success'}]}
    assert test_db_session.execute(select(RuntimeOutboxEvent)).scalars().all() == []


def test_preview_failure_commits_request_and_engine_run_together(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)
    engine_run = _create_preview_engine_run(test_db_session)

    failed = compute_requests_service.mark_request_failed(
        test_db_session,
        request.id,
        error_message='preview failed',
        worker_id=worker_id,
        claim_token=claim_token,
        lease_generation=lease_generation,
        response_envelope=_response(
            request,
            {'error': 'preview failed', 'status_code': 500},
            status=enums_pb2.COMPUTE_REQUEST_STATUS_FAILED,
            error_message='preview failed',
        ),
        engine_run_finalization=compute_requests_service.EngineRunFinalization(
            run_id=engine_run.id,
            fields={
                'status': EngineRunStatus.FAILED.value,
                'result_json': {'results': [{'status': 'failed'}]},
                'error_message': 'preview failed',
                'completed_at': datetime.now(UTC),
                'progress': 0.0,
            },
        ),
    )

    assert failed is not None
    test_db_session.expire_all()
    stored_request = test_db_session.get(ComputeRequest, request.id)
    stored_run = test_db_session.get(EngineRun, engine_run.id)
    assert stored_request is not None
    assert stored_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert stored_run is not None
    assert stored_run.status == EngineRunStatus.FAILED.value
    assert stored_run.error_message == 'preview failed'
    assert stored_run.result_json == {'results': [{'status': 'failed'}]}


def test_preview_completion_rolls_back_when_engine_run_is_already_cancelled(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        request_json=_preview_payload(),
    )
    worker_id, claim_token, lease_generation = _claim_identity(test_db_session, request)
    engine_run = _create_preview_engine_run(test_db_session)
    engine_run.status = EngineRunStatus.CANCELLED.value
    test_db_session.add(engine_run)
    test_db_session.commit()

    with pytest.raises(ValueError, match='rejected its terminal status transition'):
        compute_requests_service.mark_request_completed(
            test_db_session,
            request.id,
            worker_id=worker_id,
            claim_token=claim_token,
            lease_generation=lease_generation,
            response_envelope=_response(
                request,
                {'step_id': 'source', 'columns': [], 'column_types': {}, 'data': [], 'total_rows': 0, 'page': 1, 'page_size': 100},
            ),
            engine_run_finalization=compute_requests_service.EngineRunFinalization(
                run_id=engine_run.id,
                fields={
                    'status': EngineRunStatus.SUCCESS.value,
                    'result_json': {'results': [{'status': 'success'}]},
                    'completed_at': datetime.now(UTC),
                    'progress': 1.0,
                },
            ),
        )

    test_db_session.rollback()
    test_db_session.expire_all()
    stored_request = test_db_session.get(ComputeRequest, request.id)
    stored_run = test_db_session.get(EngineRun, engine_run.id)
    assert stored_request is not None
    assert stored_request.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert stored_run is not None
    assert stored_run.status == EngineRunStatus.CANCELLED.value


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


def test_engine_status_response_restores_enum_token_and_zero_defaults(test_db_session) -> None:
    request = _create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_SPAWN_ENGINE,
        request_json={
            'engine_identity': {
                'scope': 'analysis_interactive',
                'reuse_policy': 'shared',
                'analysis_id': 'analysis-1',
                'resource_id': 'analysis-1',
            },
            'resource_config': {},
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
                'analysis_id': 'analysis-1',
                'resource_id': 'analysis-1',
                'status': 'ENGINE_STATUS_HEALTHY',
                'lifecycle_status': 'ENGINE_INSTANCE_STATUS_IDLE',
                'defaults': {},
            },
        ),
    )
    assert completed is not None

    assert compute_requests_service.response_payload(completed) == {
        'analysis_id': 'analysis-1',
        'resource_id': 'analysis-1',
        'status': 1,
        'lifecycle_status': 'idle',
        'defaults': {'max_threads': 0, 'max_memory_mb': 0, 'streaming_chunk_size': 0},
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
    engine_run = _create_preview_engine_run(test_db_session)
    assert compute_requests_service.claim_next_request(test_db_session, worker_id='worker-2') is None
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
        engine_run_finalization=compute_requests_service.EngineRunFinalization(
            run_id=engine_run.id,
            fields={
                'status': EngineRunStatus.SUCCESS.value,
                'result_json': {'results': [{'status': 'stale'}]},
                'completed_at': datetime.now(UTC),
                'progress': 1.0,
            },
        ),
    )
    assert stale_completion is None
    test_db_session.expire_all()
    stored_run = test_db_session.get(EngineRun, engine_run.id)
    assert stored_run is not None
    assert stored_run.status == EngineRunStatus.RUNNING.value
    assert stored_run.result_json == {}

    renewed = compute_requests_service.renew_request_lease(
        test_db_session,
        request.id,
        worker_id='worker-2',
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
    )
    assert renewed.outcome is TransitionOutcome.APPLIED
    assert renewed.value is not None
    assert renewed.value.last_renewed_at is not None
    assert renewed.value.lease_expires_at is not None
    assert abs((renewed.value.lease_expires_at - renewed.value.last_renewed_at).total_seconds() - settings.runtime_work_lease_ttl_seconds) < 0.01


def test_compute_request_lease_batch_renews_valid_claims_only(test_db_session) -> None:
    worker_id = 'worker-batch-renewal'
    requests = []
    for index in range(2):
        request_json = _preview_payload()
        request_json['analysis_id'] = f'analysis-{index}'
        analysis_pipeline = cast(dict[str, object], request_json['analysis_pipeline'])
        analysis_pipeline['analysis_id'] = f'analysis-{index}'
        request_json['row_limit'] = 100 + index
        requests.append(
            _create_request(
                test_db_session,
                namespace='default',
                kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                request_json=request_json,
            )
        )
    for request in requests:
        test_db_session.add(request)
    test_db_session.commit()

    claims = [compute_requests_service.claim_next_request(test_db_session, worker_id=worker_id) for _ in requests]
    assert all(claim is not None and claim.lease_expires_at is not None for claim in claims)
    first, stale = claims
    assert first is not None and stale is not None
    assert first.claim_token is not None and stale.claim_token is not None
    assert first.lease_expires_at is not None and stale.lease_expires_at is not None
    first_expiry = first.lease_expires_at
    stale_expiry = stale.lease_expires_at

    update_statements = 0

    def count_lease_updates(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal update_statements
        normalized = statement.upper()
        if normalized.lstrip().startswith('UPDATE') and 'COMPUTE_REQUESTS' in normalized:
            update_statements += 1

    engine = test_db_session.get_bind()
    event.listen(engine, 'before_cursor_execute', count_lease_updates)
    try:
        renewed_ids = compute_requests_service.renew_request_leases(
            test_db_session,
            [
                compute_requests_service.ComputeRequestLeaseClaim(
                    request_id=first.id,
                    claim_token=first.claim_token,
                    lease_generation=first.lease_generation,
                ),
                compute_requests_service.ComputeRequestLeaseClaim(
                    request_id=stale.id,
                    claim_token='stale-token',
                    lease_generation=stale.lease_generation,
                ),
            ],
            worker_id=worker_id,
        )
    finally:
        event.remove(engine, 'before_cursor_execute', count_lease_updates)

    assert renewed_ids == {first.id}
    assert update_statements == 1
    test_db_session.expire_all()
    stored_first = test_db_session.get(ComputeRequest, first.id)
    stored_stale = test_db_session.get(ComputeRequest, stale.id)
    assert stored_first is not None and stored_first.lease_expires_at > first_expiry
    assert stored_stale is not None and stored_stale.lease_expires_at == stale_expiry


def test_expired_request_is_failed_after_attempt_exhaustion(test_db_session, monkeypatch) -> None:
    refreshes: list[dict[str, object]] = []
    monkeypatch.setattr(
        compute_requests_service.runtime_work_service,
        'refresh_pending_work',
        lambda _session, **kwargs: refreshes.append(kwargs),
    )
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

    assert compute_requests_service.reconcile_expired_requests(test_db_session, namespace='default') == 1

    test_db_session.refresh(claimed)
    assert claimed.status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert claimed.error_message == 'Compute request exhausted 1 execution attempts'
    assert claimed.response_envelope is not None
    assert response_payload(_stored_response(claimed))['error'] == 'Compute request exhausted 1 execution attempts'
    assert len(refreshes) == 1
    assert refreshes[0]['namespace'] == 'default'
    assert refreshes[0]['kind'] == compute_requests_service.RuntimeWorkKind.COMPUTE


def test_reconcile_expired_requests_is_scoped_to_target_namespace(test_db_session, monkeypatch) -> None:
    refreshes: list[dict[str, object]] = []
    monkeypatch.setattr(
        compute_requests_service.runtime_work_service,
        'refresh_pending_work',
        lambda _session, **kwargs: refreshes.append(kwargs),
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    requests = []
    for namespace in ('tenant-a', 'tenant-b'):
        request = _create_request(
            test_db_session,
            namespace=namespace,
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            request_json=_preview_payload(),
        )
        request.status = enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
        request.attempts = 1
        request.max_attempts = 1
        request.lease_owner = f'worker-{namespace}'
        request.claim_token = f'claim-{namespace}'
        request.lease_generation = 3
        request.lease_expires_at = expired_at
        test_db_session.add(request)
        requests.append(request)
    test_db_session.commit()

    reconciled = compute_requests_service.reconcile_expired_requests(test_db_session, namespace='tenant-a')

    assert reconciled == 1
    for request in requests:
        test_db_session.refresh(request)
    assert requests[0].status == enums_pb2.COMPUTE_REQUEST_STATUS_FAILED
    assert requests[1].status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
    assert [refresh['namespace'] for refresh in refreshes] == ['tenant-a']
    assert refreshes[0]['kind'] == compute_requests_service.RuntimeWorkKind.COMPUTE
