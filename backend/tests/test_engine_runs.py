import uuid
from datetime import UTC, datetime

from modules.engine_runs import service as engine_run_service
from modules.engine_runs.models import EngineRun


def _create_payload(kind: str, status: str, analysis_id: str | None = None, datasource_id: str | None = None):
    return engine_run_service.create_engine_run_payload(
        analysis_id=analysis_id,
        datasource_id=datasource_id or str(uuid.uuid4()),
        kind=kind,
        status=status,
        request_json={'kind': kind},
        result_json={'row_count': 1},
        created_at=datetime.now(UTC),
    )


def test_create_engine_run_persists(test_db_session):
    payload = _create_payload('preview', 'success', analysis_id='analysis-1', datasource_id='ds-1')

    result = engine_run_service.create_engine_run(test_db_session, payload)
    run = test_db_session.get(EngineRun, result.id)

    assert run is not None
    assert run.kind == 'preview'
    assert run.status == 'success'
    assert run.analysis_id == 'analysis-1'


def test_list_engine_runs_filters(test_db_session):
    payload_a = _create_payload('preview', 'success', analysis_id='analysis-a', datasource_id='ds-a')
    payload_b = _create_payload('export', 'failed', analysis_id='analysis-b', datasource_id='ds-b')
    engine_run_service.create_engine_run(test_db_session, payload_a)
    engine_run_service.create_engine_run(test_db_session, payload_b)

    result = engine_run_service.list_engine_runs(test_db_session, analysis_id='analysis-a')
    assert len(result) == 1
    assert result[0].analysis_id == 'analysis-a'

    result = engine_run_service.list_engine_runs(test_db_session, status='failed')
    assert len(result) == 1
    assert result[0].status == 'failed'


def test_list_engine_runs_pagination(test_db_session):
    for idx in range(3):
        payload = _create_payload('preview', 'success', analysis_id=f'analysis-{idx}', datasource_id=f'ds-{idx}')
        engine_run_service.create_engine_run(test_db_session, payload)

    first = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=0)
    second = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1
