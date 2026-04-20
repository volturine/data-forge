import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from core.database import run_db
from core.namespace import reset_namespace, set_namespace_context
from main import app
from modules.engine_runs import service as engine_run_service
from modules.engine_runs.models import EngineRun
from modules.engine_runs.schemas import EngineRunKind, EngineRunStatus


def _create_payload(
    kind: EngineRunKind | str,
    status: EngineRunStatus | str,
    analysis_id: str | None = None,
    datasource_id: str | None = None,
):
    return engine_run_service.create_engine_run_payload(
        analysis_id=analysis_id,
        datasource_id=datasource_id or str(uuid.uuid4()),
        kind=kind,
        status=status,
        request_json={'kind': str(kind)},
        result_json={'row_count': 1},
        created_at=datetime.now(UTC),
    )


def test_create_engine_run_persists(test_db_session):
    payload = _create_payload(EngineRunKind.PREVIEW, EngineRunStatus.SUCCESS, analysis_id='analysis-1', datasource_id='ds-1')

    result = engine_run_service.create_engine_run(test_db_session, payload)
    run = test_db_session.get(EngineRun, result.id)

    assert run is not None
    assert run.kind == EngineRunKind.PREVIEW
    assert run.status == EngineRunStatus.SUCCESS
    assert run.analysis_id == 'analysis-1'


def test_create_engine_run_persists_execution_entries(test_db_session):
    payload = engine_run_service.create_engine_run_payload(
        analysis_id='analysis-1',
        datasource_id='ds-1',
        kind=EngineRunKind.PREVIEW,
        status=EngineRunStatus.SUCCESS,
        request_json={'kind': 'preview'},
        result_json={'row_count': 1},
        execution_entries=[
            {
                'key': 'initial_read',
                'label': 'Initial Read',
                'category': 'read',
                'order': 0,
                'duration_ms': 12.5,
                'share_pct': 25.0,
                'optimized_plan': None,
                'unoptimized_plan': None,
                'metadata': None,
            }
        ],
        created_at=datetime.now(UTC),
    )

    result = engine_run_service.create_engine_run(test_db_session, payload)
    run = test_db_session.get(EngineRun, result.id)

    assert run is not None
    assert isinstance(run.result_json, dict)
    assert run.result_json['execution_entries'][0]['key'] == 'initial_read'
    assert result.execution_entries[0].key == 'initial_read'


def test_list_engine_runs_filters(test_db_session):
    payload_a = _create_payload(EngineRunKind.PREVIEW, EngineRunStatus.SUCCESS, analysis_id='analysis-a', datasource_id='ds-a')
    payload_b = _create_payload(EngineRunKind.DOWNLOAD, EngineRunStatus.FAILED, analysis_id='analysis-b', datasource_id='ds-b')
    payload_c = _create_payload(EngineRunKind.DOWNLOAD, EngineRunStatus.CANCELLED, analysis_id='analysis-c', datasource_id='ds-c')
    engine_run_service.create_engine_run(test_db_session, payload_a)
    engine_run_service.create_engine_run(test_db_session, payload_b)
    engine_run_service.create_engine_run(test_db_session, payload_c)

    result = engine_run_service.list_engine_runs(test_db_session, analysis_id='analysis-a')
    assert len(result) == 1
    assert result[0].analysis_id == 'analysis-a'

    result = engine_run_service.list_engine_runs(test_db_session, status=EngineRunStatus.FAILED)
    assert len(result) == 1
    assert result[0].status == EngineRunStatus.FAILED

    result = engine_run_service.list_engine_runs(test_db_session, status=EngineRunStatus.CANCELLED)
    assert len(result) == 1
    assert result[0].status == EngineRunStatus.CANCELLED


def test_list_engine_runs_pagination(test_db_session):
    for idx in range(3):
        payload = _create_payload(EngineRunKind.PREVIEW, EngineRunStatus.SUCCESS, analysis_id=f'analysis-{idx}', datasource_id=f'ds-{idx}')
        engine_run_service.create_engine_run(test_db_session, payload)

    first = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=0)
    second = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1


def test_update_engine_run_reuses_existing_row(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-1',
            datasource_id='ds-1',
            kind=EngineRunKind.DATASOURCE_UPDATE,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'datasource_update'},
            result_json={'current_output_name': 'output_salary_predictions'},
            created_at=datetime.now(UTC),
        ),
    )

    updated = engine_run_service.update_engine_run(
        test_db_session,
        created.id,
        status=EngineRunStatus.SUCCESS,
        progress=1.0,
        duration_ms=321,
        completed_at=datetime.now(UTC),
        result_json={'datasource_name': 'output_salary_predictions'},
    )

    rows = engine_run_service.list_engine_runs(test_db_session, datasource_id='ds-1')
    assert len(rows) == 1
    assert updated.id == created.id
    assert updated.status == EngineRunStatus.SUCCESS
    assert updated.result_json is not None
    assert updated.result_json['datasource_name'] == 'output_salary_predictions'


def test_update_engine_run_replaces_result_json_when_merge_disabled(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-live-merge',
            datasource_id='output-ds-1',
            kind=EngineRunKind.DATASOURCE_UPDATE,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'datasource_update'},
            result_json={'current_output_name': 'stale-output', 'logs': [{'message': 'old'}]},
            created_at=datetime.now(UTC),
        ),
    )

    updated = engine_run_service.update_engine_run(
        test_db_session,
        created.id,
        status=EngineRunStatus.SUCCESS,
        progress=1.0,
        duration_ms=321,
        completed_at=datetime.now(UTC),
        result_json={'datasource_name': 'output_salary_predictions'},
        merge_result_json=False,
    )

    assert updated.result_json is not None
    assert updated.result_json['datasource_name'] == 'output_salary_predictions'
    assert 'current_output_name' not in updated.result_json
    assert 'logs' not in updated.result_json


def test_list_engine_runs_http_returns_filtered_runs(client, test_db_session) -> None:
    analysis_id = str(uuid.uuid4())
    engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id=analysis_id,
            datasource_id='ds-list',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.SUCCESS,
            request_json={'kind': 'preview'},
            result_json={'row_count': 2},
            created_at=datetime.now(UTC),
        ),
    )
    engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id=str(uuid.uuid4()),
            datasource_id='ds-other',
            kind=EngineRunKind.DOWNLOAD,
            status=EngineRunStatus.FAILED,
            request_json={'kind': 'download'},
            result_json={'row_count': 5},
            created_at=datetime.now(UTC),
        ),
    )

    response = client.get(
        '/api/v1/engine-runs',
        params={'analysis_id': analysis_id, 'status': 'success'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]['analysis_id'] == analysis_id
    assert payload[0]['status'] == 'success'


def test_get_engine_run_http_returns_full_run(client, test_db_session) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-detail',
            datasource_id='ds-detail',
            kind=EngineRunKind.ROW_COUNT,
            status=EngineRunStatus.SUCCESS,
            request_json={'kind': 'row_count'},
            result_json={'row_count': 9, 'schema': {'value': 'Int64'}},
            created_at=datetime.now(UTC),
            duration_ms=42,
        ),
    )

    response = client.get(f'/api/v1/engine-runs/{created.id}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['id'] == created.id
    assert payload['kind'] == 'row_count'
    assert payload['result_json']['row_count'] == 9


def test_get_engine_run_http_returns_404_for_missing_run(client) -> None:
    response = client.get(f'/api/v1/engine-runs/{uuid.uuid4()}')

    assert response.status_code == 404
    assert response.json() == {'detail': 'Engine run not found'}


def test_engine_runs_http_respects_namespace() -> None:
    payload = engine_run_service.create_engine_run_payload(
        analysis_id='analysis-default',
        datasource_id='ds-default',
        kind=EngineRunKind.PREVIEW,
        status=EngineRunStatus.SUCCESS,
        request_json={'kind': 'preview'},
        result_json={'row_count': 1},
        created_at=datetime.now(UTC),
    )

    default = set_namespace_context('default')
    try:
        run_db(engine_run_service.create_engine_run, payload)
    finally:
        reset_namespace(default)

    with TestClient(app) as client:
        default_response = client.get('/api/v1/engine-runs')
        beta_response = client.get('/api/v1/engine-runs', headers={'X-Namespace': 'beta'})

    assert default_response.status_code == 200
    assert len(default_response.json()) == 1
    assert default_response.json()[0]['analysis_id'] == 'analysis-default'
    assert beta_response.status_code == 200
    assert beta_response.json() == []
