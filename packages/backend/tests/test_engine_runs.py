import uuid
from datetime import UTC, datetime, timedelta

from backend_core import build_runs_service, engine_runs_service as engine_run_service
from backend_core.domain.build_runs.models import BuildRunStatus
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.engine_runs.models import EngineRun


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
    payload = _create_payload(
        EngineRunKind.PREVIEW,
        EngineRunStatus.SUCCESS,
        analysis_id='analysis-1',
        datasource_id='ds-1',
    )

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
    payload_a = _create_payload(
        EngineRunKind.PREVIEW,
        EngineRunStatus.SUCCESS,
        analysis_id='analysis-a',
        datasource_id='ds-a',
    )
    payload_b = _create_payload(
        EngineRunKind.DOWNLOAD,
        EngineRunStatus.FAILED,
        analysis_id='analysis-b',
        datasource_id='ds-b',
    )
    payload_c = _create_payload(
        EngineRunKind.DOWNLOAD,
        EngineRunStatus.CANCELLED,
        analysis_id='analysis-c',
        datasource_id='ds-c',
    )
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
        payload = _create_payload(
            EngineRunKind.PREVIEW,
            EngineRunStatus.SUCCESS,
            analysis_id=f'analysis-{idx}',
            datasource_id=f'ds-{idx}',
        )
        engine_run_service.create_engine_run(test_db_session, payload)

    first = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=0)
    second = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1


def test_list_engine_runs_excludes_build_kind(test_db_session):
    engine_run_service.create_engine_run(
        test_db_session,
        _create_payload(
            EngineRunKind.BUILD,
            EngineRunStatus.SUCCESS,
            analysis_id='analysis-build',
            datasource_id='ds-build',
        ),
    )
    engine_run_service.create_engine_run(
        test_db_session,
        _create_payload(
            EngineRunKind.PREVIEW,
            EngineRunStatus.SUCCESS,
            analysis_id='analysis-preview',
            datasource_id='ds-preview',
        ),
    )
    engine_run_service.create_engine_run(
        test_db_session,
        _create_payload(
            EngineRunKind.INGEST,
            EngineRunStatus.SUCCESS,
            analysis_id=None,
            datasource_id='ds-ingest',
        ),
    )

    rows = engine_run_service.list_engine_runs(test_db_session)

    assert len(rows) == 2
    assert {row.kind for row in rows} == {EngineRunKind.PREVIEW, EngineRunKind.INGEST}
    assert engine_run_service.list_engine_runs(test_db_session, kind=EngineRunKind.BUILD) == []


def test_update_engine_run_reuses_existing_row(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-1',
            datasource_id='ds-1',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'preview'},
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
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'preview'},
            result_json={
                'current_output_name': 'stale-output',
                'logs': [{'message': 'old'}],
            },
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


def test_update_engine_run_keeps_terminal_run_immutable(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-terminal',
            datasource_id='ds-terminal',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.SUCCESS,
            request_json={'kind': 'preview'},
            result_json={'row_count': 1},
            created_at=datetime.now(UTC),
        ),
    )

    updated = engine_run_service.update_engine_run(
        test_db_session,
        created.id,
        status=EngineRunStatus.FAILED,
        error_message='should be ignored',
        result_json={'row_count': 999},
        progress=0.25,
    )

    assert updated.status == EngineRunStatus.SUCCESS
    stored = test_db_session.get(EngineRun, created.id)
    assert stored is not None
    assert stored.status == EngineRunStatus.SUCCESS
    assert stored.error_message is None


def test_update_engine_run_reports_rejected_terminal_conflict(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-terminal-conflict',
            datasource_id='ds-terminal',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.SUCCESS,
            request_json={'kind': 'preview'},
            result_json={'row_count': 1},
            created_at=datetime.now(UTC),
        ),
    )

    rejected = engine_run_service.update_engine_run(
        test_db_session,
        created.id,
        status=EngineRunStatus.FAILED,
        error_message='should be ignored',
    )

    assert rejected.applied is False
    assert rejected.status == EngineRunStatus.SUCCESS
    stored = test_db_session.get(EngineRun, created.id)
    assert stored is not None
    assert stored.result_json == {'row_count': 1}
    assert stored.progress == 0.0

    idempotent = engine_run_service.update_engine_run(
        test_db_session,
        created.id,
        status=EngineRunStatus.SUCCESS,
        error_message='still ignored',
    )
    assert idempotent.applied is True
    assert idempotent.status == EngineRunStatus.SUCCESS


def test_update_engine_run_applies_changes_to_running_run(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-running-applied',
            datasource_id='ds-1',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'preview'},
            result_json=None,
            created_at=datetime.now(UTC),
        ),
    )

    updated = engine_run_service.update_engine_run(
        test_db_session,
        created.id,
        status=EngineRunStatus.SUCCESS,
        execution_entries=[],
        result_json={'row_count': 5},
    )

    assert updated.applied is True
    assert updated.status == EngineRunStatus.SUCCESS
    stored = test_db_session.get(EngineRun, created.id)
    assert stored is not None
    assert stored.result_json == {'row_count': 5, 'execution_entries': []}


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


def test_engine_runs_http_respects_namespace(client, test_db_session) -> None:
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
        engine_run_service.create_engine_run(test_db_session, payload)
    finally:
        reset_namespace(default)

    default_response = client.get('/api/v1/engine-runs')
    beta_response = client.get('/api/v1/engine-runs', headers={'X-Namespace': 'beta'})

    assert default_response.status_code == 200
    assert len(default_response.json()) == 1
    assert default_response.json()[0]['analysis_id'] == 'analysis-default'
    assert beta_response.status_code == 200
    assert beta_response.json() == []


def _completed_build_run(
    test_db_session,
    *,
    analysis_id: str,
    duration_ms: int,
    started_at: datetime,
    datasource_id: str = 'ds-1',
):
    run = build_runs_service.create_build_run(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        analysis_id=analysis_id,
        analysis_name='Duration Analysis',
        request_json={'analysis_id': analysis_id},
        starter_json={'triggered_by': 'test'},
        status=BuildRunStatus.COMPLETED,
        current_kind=EngineRunKind.BUILD,
        current_datasource_id=datasource_id,
        created_at=started_at,
        started_at=started_at,
    )
    run.duration_ms = duration_ms
    run.elapsed_ms = duration_ms
    run.completed_at = started_at + timedelta(milliseconds=duration_ms)
    test_db_session.add(run)
    test_db_session.commit()
    test_db_session.refresh(run)
    return run


def test_duration_stats_for_builds_uses_build_runs(test_db_session) -> None:
    analysis_id = 'analysis-duration-stats'
    now = datetime.now(UTC)
    for index, duration in enumerate((1000, 2000, 3000, 4000)):
        run = _completed_build_run(
            test_db_session,
            analysis_id=analysis_id,
            duration_ms=duration,
            started_at=now + timedelta(seconds=index),
            datasource_id=f'ds-{index}',
        )
        assert run.duration_ms == duration

    stats = engine_run_service.duration_stats(
        test_db_session,
        analysis_id=analysis_id,
        kind=EngineRunKind.BUILD,
        limit=20,
    )

    assert len(stats.runs) == 4
    assert stats.avg_duration_ms == 2500.0
    assert stats.p50_duration_ms == 2500.0
    assert stats.p95_duration_ms is not None
    assert stats.trend.direction in {'decreasing', 'stable', 'increasing'}
    assert stats.trend.sample_size == 4
    assert stats.trend.summary
    assert [run.duration_ms for run in stats.runs] == [1000, 2000, 3000, 4000]


def test_duration_stats_http_endpoint(client, test_db_session) -> None:
    analysis_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    _completed_build_run(
        test_db_session,
        analysis_id=analysis_id,
        duration_ms=1500,
        started_at=now,
        datasource_id='ds-http',
    )

    response = client.get(
        '/api/v1/engine-runs/stats',
        params={'analysis_id': analysis_id, 'kind': 'build', 'limit': 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload['runs']) == 1
    assert payload['runs'][0]['duration_ms'] == 1500
    assert payload['avg_duration_ms'] == 1500.0
    assert payload['trend']['direction'] == 'insufficient_data'
    assert '4' in payload['trend']['summary']


def test_duration_stats_trend_reports_increasing_when_recent_runs_take_longer(
    test_db_session,
) -> None:
    analysis_id = 'analysis-duration-increasing'
    now = datetime.now(UTC)
    # Older half short, newer half long → increasing duration
    for index, duration in enumerate((1000, 1100, 5000, 5200)):
        _completed_build_run(
            test_db_session,
            analysis_id=analysis_id,
            duration_ms=duration,
            started_at=now + timedelta(seconds=index),
            datasource_id=f'ds-inc-{index}',
        )

    stats = engine_run_service.duration_stats(
        test_db_session,
        analysis_id=analysis_id,
        kind=EngineRunKind.BUILD,
        limit=20,
    )
    assert stats.trend.direction == 'increasing'
    assert stats.trend.change_pct is not None and stats.trend.change_pct >= 10
    assert stats.trend.older_count == 2
    assert stats.trend.recent_count == 2
    assert 'increasing' in stats.trend.summary.lower()


def test_duration_stats_trend_reports_decreasing_when_recent_runs_are_shorter(
    test_db_session,
) -> None:
    analysis_id = 'analysis-duration-decreasing'
    now = datetime.now(UTC)
    for index, duration in enumerate((5000, 5200, 1000, 1100)):
        _completed_build_run(
            test_db_session,
            analysis_id=analysis_id,
            duration_ms=duration,
            started_at=now + timedelta(seconds=index),
            datasource_id=f'ds-dec-{index}',
        )

    stats = engine_run_service.duration_stats(
        test_db_session,
        analysis_id=analysis_id,
        kind=EngineRunKind.BUILD,
        limit=20,
    )
    assert stats.trend.direction == 'decreasing'
    assert stats.trend.change_pct is not None and stats.trend.change_pct <= -10
    assert 'decreasing' in stats.trend.summary.lower()


def test_duration_stats_for_preview_kind_uses_engine_runs(test_db_session) -> None:
    analysis_id = 'analysis-preview-stats'
    now = datetime.now(UTC)
    for duration in (500, 1500):
        engine_run_service.create_engine_run(
            test_db_session,
            engine_run_service.create_engine_run_payload(
                analysis_id=analysis_id,
                datasource_id='ds-preview-stats',
                kind=EngineRunKind.PREVIEW,
                status=EngineRunStatus.SUCCESS,
                request_json={'kind': 'preview'},
                result_json={'row_count': 1},
                created_at=now,
                duration_ms=duration,
            ),
        )

    stats = engine_run_service.duration_stats(
        test_db_session,
        analysis_id=analysis_id,
        kind=EngineRunKind.PREVIEW,
        limit=20,
    )

    assert len(stats.runs) == 2
    assert stats.avg_duration_ms == 1000.0
