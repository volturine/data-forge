import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect
from sqlmodel import Session

from modules.engine_runs import schemas as engine_run_schemas, service as engine_run_service, watchers as engine_run_watchers
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
    engine_run_service.create_engine_run(test_db_session, payload_a)
    engine_run_service.create_engine_run(test_db_session, payload_b)

    result = engine_run_service.list_engine_runs(test_db_session, analysis_id='analysis-a')
    assert len(result) == 1
    assert result[0].analysis_id == 'analysis-a'

    result = engine_run_service.list_engine_runs(test_db_session, status=EngineRunStatus.FAILED)
    assert len(result) == 1
    assert result[0].status == EngineRunStatus.FAILED


def test_list_engine_runs_pagination(test_db_session):
    for idx in range(3):
        payload = _create_payload(EngineRunKind.PREVIEW, EngineRunStatus.SUCCESS, analysis_id=f'analysis-{idx}', datasource_id=f'ds-{idx}')
        engine_run_service.create_engine_run(test_db_session, payload)

    first = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=0)
    second = engine_run_service.list_engine_runs(test_db_session, limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1


def test_list_engine_runs_derives_unified_execution_entries_from_legacy_fields(test_db_session):
    run = EngineRun(
        id=str(uuid.uuid4()),
        analysis_id='analysis-legacy',
        datasource_id='ds-legacy',
        kind=EngineRunKind.PREVIEW,
        status=EngineRunStatus.SUCCESS,
        request_json={},
        result_json={'query_plans': {'optimized': 'opt plan', 'unoptimized': 'raw plan'}},
        created_at=datetime.now(UTC),
        duration_ms=100,
        step_timings={'filter_1': 35.0, 'select_2': 15.0},
        query_plan='fallback plan',
        progress=1.0,
    )
    test_db_session.add(run)
    test_db_session.commit()

    result = engine_run_service.list_engine_runs(test_db_session, analysis_id='analysis-legacy')

    assert len(result) == 1
    entries = result[0].execution_entries
    assert [entry.key for entry in entries] == ['query_plan', 'filter_1', 'select_2']
    assert entries[0].optimized_plan == 'opt plan'
    assert entries[0].unoptimized_plan == 'raw plan'
    assert entries[1].label == 'Filter 1'
    assert entries[2].label == 'Select 2'


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


def test_apply_live_event_enriches_existing_run(test_db_session):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-live',
            datasource_id='output-ds-1',
            kind=EngineRunKind.DATASOURCE_UPDATE,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'datasource_update'},
            result_json={'steps': [], 'query_plans': [], 'resources': [], 'logs': []},
            created_at=datetime.now(UTC),
        ),
    )

    engine_run_service.apply_live_event(
        test_db_session,
        created.id,
        {
            'type': 'step_complete',
            'build_step_index': 0,
            'step_index': 0,
            'step_id': 'tab-1:initial_read',
            'step_name': 'Initial Read',
            'step_type': 'read',
            'duration_ms': 12,
            'tab_id': 'tab-1',
            'tab_name': 'View',
            'current_output_id': 'output-ds-1',
            'current_output_name': 'output_salary_predictions',
        },
    )
    enriched = engine_run_service.apply_live_event(
        test_db_session,
        created.id,
        {
            'type': 'step_complete',
            'build_step_index': 1,
            'step_index': 1,
            'step_id': 'step-1',
            'step_name': 'Filter rows',
            'step_type': 'filter',
            'duration_ms': 25,
            'row_count': 3,
            'tab_id': 'tab-1',
            'tab_name': 'View',
            'current_output_id': 'output-ds-1',
            'current_output_name': 'output_salary_predictions',
        },
    )

    assert enriched is not None
    assert enriched.status == EngineRunStatus.RUNNING
    assert enriched.result_json is not None
    assert enriched.result_json['current_output_name'] == 'output_salary_predictions'
    steps = enriched.result_json['steps']
    assert isinstance(steps, list)
    assert [step['step_name'] for step in steps] == ['Initial Read', 'Filter rows']
    assert enriched.execution_entries[0].label == 'Initial Read'
    assert enriched.execution_entries[1].label == 'Filter rows'
    assert enriched.step_timings == {'filter_1': 25.0}


def test_update_engine_run_preserves_live_metadata_from_other_session(test_db_session, test_engine):
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-live-merge',
            datasource_id='output-ds-1',
            kind=EngineRunKind.DATASOURCE_UPDATE,
            status=EngineRunStatus.RUNNING,
            request_json={'kind': 'datasource_update'},
            result_json={'steps': [], 'query_plans': [], 'resources': [], 'logs': []},
            created_at=datetime.now(UTC),
        ),
    )

    with Session(test_engine) as other_session:
        engine_run_service.apply_live_event(
            other_session,
            created.id,
            {
                'type': 'step_complete',
                'build_step_index': 0,
                'step_index': 0,
                'step_id': 'tab-1:initial_read',
                'step_name': 'Initial Read',
                'step_type': 'read',
                'duration_ms': 12,
                'tab_id': 'tab-1',
                'tab_name': 'View',
                'current_output_id': 'output-ds-1',
                'current_output_name': 'output_salary_predictions',
            },
        )
        engine_run_service.apply_live_event(
            other_session,
            created.id,
            {
                'type': 'resources',
                'emitted_at': '2026-04-08T12:00:00Z',
                'cpu_percent': 25,
                'memory_mb': 128,
                'memory_limit_mb': 512,
                'active_threads': 4,
                'max_threads': 8,
            },
        )
        engine_run_service.apply_live_event(
            other_session,
            created.id,
            {
                'type': 'log',
                'emitted_at': '2026-04-08T12:00:01Z',
                'level': 'info',
                'message': 'Running build',
            },
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

    assert updated.result_json is not None
    assert updated.result_json['datasource_name'] == 'output_salary_predictions'
    assert updated.result_json['current_output_name'] == 'output_salary_predictions'
    assert updated.result_json['steps'][0]['step_name'] == 'Initial Read'
    assert updated.result_json['resources'][0]['cpu_percent'] == 25
    assert updated.result_json['logs'][0]['message'] == 'Running build'


def test_engine_run_list_websocket_sends_snapshot_and_updates(client, test_db_session) -> None:
    with client.websocket_connect('/api/v1/engine-runs/ws?namespace=default') as websocket:
        snapshot = websocket.receive_json()
        created = engine_run_service.create_engine_run(
            test_db_session,
            engine_run_service.create_engine_run_payload(
                analysis_id='analysis-ws',
                datasource_id='ds-ws',
                kind=EngineRunKind.PREVIEW,
                status=EngineRunStatus.RUNNING,
                request_json={'kind': 'preview'},
                result_json={'row_count': 1},
                created_at=datetime.now(UTC),
            ),
        )
        created_message = websocket.receive_json()
        engine_run_service.apply_live_event(
            test_db_session,
            created.id,
            {
                'type': 'progress',
                'progress': 0.5,
                'elapsed_ms': 150,
                'current_step': 'Filter rows',
                'current_step_index': 1,
                'total_steps': 3,
            },
        )
        live_message = websocket.receive_json()
        engine_run_service.update_engine_run(
            test_db_session,
            created.id,
            status=EngineRunStatus.SUCCESS,
            progress=1.0,
            duration_ms=300,
            completed_at=datetime.now(UTC),
            result_json={'row_count': 2},
        )
        terminal_message = websocket.receive_json()

    assert snapshot == {'type': 'snapshot', 'runs': []}
    assert created_message['type'] == 'snapshot'
    assert created_message['runs'][0]['id'] == created.id
    assert created_message['runs'][0]['status'] == 'running'
    assert live_message['type'] == 'update'
    assert live_message['run']['id'] == created.id
    assert live_message['run']['progress'] == 0.5
    assert live_message['run']['current_step'] == 'Filter rows'
    assert terminal_message['type'] == 'update'
    assert terminal_message['run']['id'] == created.id
    assert terminal_message['run']['status'] == 'success'
    assert terminal_message['run']['progress'] == 1.0


def test_engine_run_list_websocket_refreshes_snapshot_when_filtered_membership_changes(client, test_db_session) -> None:
    with client.websocket_connect('/api/v1/engine-runs/ws?namespace=default&status=running') as websocket:
        initial = websocket.receive_json()
        created = engine_run_service.create_engine_run(
            test_db_session,
            engine_run_service.create_engine_run_payload(
                analysis_id='analysis-running',
                datasource_id='ds-running',
                kind=EngineRunKind.PREVIEW,
                status=EngineRunStatus.RUNNING,
                request_json={'kind': 'preview'},
                result_json={'row_count': 1},
                created_at=datetime.now(UTC),
            ),
        )
        created_message = websocket.receive_json()
        engine_run_service.update_engine_run(
            test_db_session,
            created.id,
            status=EngineRunStatus.SUCCESS,
            progress=1.0,
            completed_at=datetime.now(UTC),
            duration_ms=250,
        )
        completed_message = websocket.receive_json()

    assert initial == {'type': 'snapshot', 'runs': []}
    assert created_message['type'] == 'snapshot'
    assert [run['id'] for run in created_message['runs']] == [created.id]
    assert completed_message == {'type': 'snapshot', 'runs': []}


def test_engine_run_broadcast_scopes_updates_by_namespace(test_db_session) -> None:
    async def scenario() -> None:
        default_socket = MagicMock()
        default_socket.send_json = AsyncMock()
        team_socket = MagicMock()
        team_socket.send_json = AsyncMock()
        params = engine_run_schemas.EngineRunListParams()

        engine_run_watchers.registry.add(
            'default',
            default_socket,
            loop=asyncio.get_running_loop(),
            params=params,
        )
        engine_run_watchers.registry.add(
            'team-a',
            team_socket,
            loop=asyncio.get_running_loop(),
            params=params,
        )

        engine_run_service.create_engine_run(
            test_db_session,
            engine_run_service.create_engine_run_payload(
                analysis_id='analysis-default',
                datasource_id='ds-default',
                kind=EngineRunKind.PREVIEW,
                status=EngineRunStatus.RUNNING,
                request_json={'kind': 'preview'},
                result_json={'row_count': 1},
                created_at=datetime.now(UTC),
            ),
        )

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        default_socket.send_json.assert_awaited_once()
        team_socket.send_json.assert_not_awaited()
        engine_run_watchers.registry.discard('default', default_socket)
        engine_run_watchers.registry.discard('team-a', team_socket)

    asyncio.run(scenario())


def test_engine_run_broadcast_skips_list_query_for_existing_watched_run_update(test_db_session) -> None:
    async def scenario() -> None:
        socket = MagicMock()
        socket.send_json = AsyncMock()
        params = engine_run_schemas.EngineRunListParams()
        created = engine_run_service.create_engine_run(
            test_db_session,
            engine_run_service.create_engine_run_payload(
                analysis_id='analysis-fast-path',
                datasource_id='ds-fast-path',
                kind=EngineRunKind.PREVIEW,
                status=EngineRunStatus.RUNNING,
                request_json={'kind': 'preview'},
                result_json={'row_count': 1},
                created_at=datetime.now(UTC),
            ),
        )

        engine_run_watchers.registry.add(
            'default',
            socket,
            loop=asyncio.get_running_loop(),
            params=params,
        )
        engine_run_watchers.registry.set_run_ids('default', socket, (created.id,))

        with patch('modules.engine_runs.service.list_engine_runs', wraps=engine_run_service.list_engine_runs) as mocked:
            engine_run_service.apply_live_event(
                test_db_session,
                created.id,
                {
                    'type': 'progress',
                    'progress': 0.5,
                    'elapsed_ms': 120,
                    'current_step': 'Filter rows',
                    'current_step_index': 1,
                    'total_steps': 3,
                },
            )

            await asyncio.sleep(0)
            await asyncio.sleep(0)

        mocked.assert_not_called()
        socket.send_json.assert_awaited_once()
        message = socket.send_json.await_args.args[0]
        assert message['type'] == 'update'
        assert message['run']['id'] == created.id
        assert message['run']['progress'] == 0.5
        engine_run_watchers.registry.discard('default', socket)

    asyncio.run(scenario())


def test_engine_run_watcher_send_swallows_expected_disconnect_cleanup(caplog) -> None:
    async def scenario() -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock(side_effect=WebSocketDisconnect())
        params = engine_run_schemas.EngineRunListParams()
        registry = engine_run_watchers.EngineRunWatcherRegistry()

        registry.add(
            'default',
            websocket,
            loop=asyncio.get_running_loop(),
            params=params,
        )

        with caplog.at_level('WARNING'):
            await registry._send('default', websocket, {'type': 'snapshot', 'runs': []})

        assert registry.watchers('default') == []
        assert 'Engine run watcher send failed' not in caplog.text

    asyncio.run(scenario())


def test_engine_run_watcher_send_logs_unexpected_failures(caplog) -> None:
    async def scenario() -> None:
        websocket = MagicMock()
        websocket.send_json = AsyncMock(side_effect=RuntimeError('boom'))
        params = engine_run_schemas.EngineRunListParams()
        registry = engine_run_watchers.EngineRunWatcherRegistry()

        registry.add(
            'default',
            websocket,
            loop=asyncio.get_running_loop(),
            params=params,
        )

        with caplog.at_level('WARNING'):
            await registry._send('default', websocket, {'type': 'snapshot', 'runs': []})

        assert registry.watchers('default') == []
        assert 'Engine run watcher send failed: boom' in caplog.text

    asyncio.run(scenario())
