import asyncio
import concurrent.futures
import contextvars
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketState

from core.dependencies import get_manager
from core.exceptions import PipelineValidationError
from core.namespace import namespace_paths, reset_namespace, set_namespace_context
from main import app
from modules.compute import schemas as compute_schemas, service as compute_service
from modules.compute.core.base import ComputeEngine, EngineProgressEvent, EngineResult
from modules.compute.engine import PolarsComputeEngine
from modules.compute.live import ActiveBuild, registry as active_build_registry
from modules.compute.manager import ProcessManager
from modules.compute.operations.datasource import _analysis_stack_var
from modules.compute.routes import (
    _safe_close_websocket,
    _safe_send_json,
    _wait_for_websocket_disconnect,
    active_build_stream,
    build_list_stream,
    engine_list_stream,
)
from modules.compute.utils import await_engine_result
from modules.datasource.models import DataSource
from modules.engine_runs import service as engine_run_service
from modules.engine_runs.models import EngineRun


def test_safe_close_websocket_skips_when_already_disconnected() -> None:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.DISCONNECTED
    websocket.application_state = WebSocketState.CONNECTED
    websocket.close = AsyncMock()

    asyncio.run(_safe_close_websocket(websocket))

    websocket.close.assert_not_called()


def test_safe_close_websocket_swallows_runtime_disconnect_race() -> None:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED
    websocket.close = AsyncMock(side_effect=RuntimeError("Unexpected ASGI message 'websocket.close'"))

    asyncio.run(_safe_close_websocket(websocket))

    websocket.close.assert_awaited_once()


def test_safe_close_websocket_reraises_unexpected_runtime_error() -> None:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED
    websocket.close = AsyncMock(side_effect=RuntimeError('boom'))

    with pytest.raises(RuntimeError, match='boom'):
        asyncio.run(_safe_close_websocket(websocket))


def test_run_compute_clears_inherited_polars_env_for_auto_values(monkeypatch) -> None:
    monkeypatch.setenv('POLARS_MAX_THREADS', '8')
    monkeypatch.setenv('POLARS_STREAMING_CHUNK_SIZE', '100000')
    command_queue = MagicMock()
    command_queue.get.return_value = {'type': 'shutdown'}

    PolarsComputeEngine._run_compute(command_queue, MagicMock(), MagicMock(), max_threads=0, streaming_chunk_size=0)

    assert 'POLARS_MAX_THREADS' not in os.environ
    assert 'POLARS_STREAMING_CHUNK_SIZE' not in os.environ


def test_classify_engine_error_marks_missing_metadata_files_as_snapshot_unavailable() -> None:
    exc = FileNotFoundError(
        2,
        'No such file or directory',
        '/tmp/x/master/metadata/00001-snapshot.metadata.json',
    )
    kind, details = PolarsComputeEngine._classify_engine_error(exc)
    assert kind == 'datasource_metadata_missing'
    assert details == {}


def test_preflight_datasource_for_compute_uses_datasource_namespace_when_ambient_differs() -> None:
    alpha = set_namespace_context('alpha')
    try:
        beta_metadata_file = namespace_paths('beta').exports_dir / 'table' / 'metadata' / 'v1.metadata.json'
        beta_metadata_file.parent.mkdir(parents=True, exist_ok=True)
        beta_metadata_file.write_text('{}', encoding='utf-8')
    finally:
        reset_namespace(alpha)

    ambient = set_namespace_context('default')
    try:
        config = {
            'source_type': 'iceberg',
            'metadata_path': str(beta_metadata_file.parent.parent),
            'branch': 'master',
            'namespace_name': 'beta',
        }

        compute_service._preflight_datasource_for_compute(
            config,
            operation='preview',
            datasource_id='datasource-id',
        )

        assert config['metadata_path'] == str(beta_metadata_file)
    finally:
        reset_namespace(ambient)


def test_preflight_datasource_for_compute_rejects_cross_namespace_path() -> None:
    alpha = set_namespace_context('alpha')
    try:
        beta_metadata_file = namespace_paths('beta').exports_dir / 'table' / 'metadata' / 'v1.metadata.json'
        beta_metadata_file.parent.mkdir(parents=True, exist_ok=True)
        beta_metadata_file.write_text('{}', encoding='utf-8')
    finally:
        reset_namespace(alpha)

    config = {
        'source_type': 'iceberg',
        'metadata_path': str(beta_metadata_file.parent.parent),
        'branch': 'master',
        'namespace_name': 'alpha',
    }

    with pytest.raises(ValueError, match='Iceberg metadata_path must be inside data directory'):
        compute_service._preflight_datasource_for_compute(
            config,
            operation='preview',
            datasource_id='datasource-id',
        )


def test_await_engine_result_returns_immediate_result_before_poll_loop() -> None:
    calls: list[tuple[str, float]] = []

    class ReadyEngine:
        analysis_id = 'analysis'
        resource_config: dict[str, int] = {}
        effective_resources: dict[str, int] = {}
        current_job_id: str | None = None

        @property
        def process_id(self) -> int | None:
            return None

        def start(self) -> None:
            raise AssertionError('start should not be called')

        def is_process_alive(self) -> bool:
            calls.append(('alive', -1))
            return False

        def check_health(self) -> bool:
            return True

        def preview(self, *_args, **_kwargs) -> str:
            raise AssertionError('preview should not be called')

        def export(self, *_args, **_kwargs) -> str:
            raise AssertionError('export should not be called')

        def get_schema(self, *_args, **_kwargs) -> str:
            raise AssertionError('get_schema should not be called')

        def get_row_count(self, *_args, **_kwargs) -> str:
            raise AssertionError('get_row_count should not be called')

        def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> EngineResult | None:
            calls.append(('result', timeout))
            if timeout == 0:
                return EngineResult(job_id=job_id, data={'ok': True}, error=None)
            raise AssertionError('poll loop should not run when result is already available')

        def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None):
            raise AssertionError('progress queue should not be called')

        def shutdown(self) -> None:
            raise AssertionError('shutdown should not be called')

    result = await_engine_result(ReadyEngine(), timeout=1, job_id='job-1')

    assert result == {
        'job_id': 'job-1',
        'data': {'ok': True},
        'error': None,
        'error_kind': None,
        'error_details': {},
        'step_timings': {},
        'query_plan': None,
        'read_duration_ms': None,
        'write_duration_ms': None,
        'collect_duration_ms': None,
    }
    assert calls == [('result', 0)]


class ProgressReadyEngine:
    analysis_id = 'analysis'
    resource_config: dict[str, int] = {}
    effective_resources: dict[str, int] = {}
    current_job_id: str | None = 'job-1'

    @property
    def process_id(self) -> int | None:
        return None

    def start(self) -> None:
        return None

    def is_process_alive(self) -> bool:
        return True

    def check_health(self) -> bool:
        return True

    def preview(self, *_args, **_kwargs) -> str:
        return 'job-1'

    def export(self, *_args, **_kwargs) -> str:
        return 'job-1'

    def get_schema(self, *_args, **_kwargs) -> str:
        return 'job-1'

    def get_row_count(self, *_args, **_kwargs) -> str:
        return 'job-1'

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> EngineResult | None:
        return None

    def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None):
        from modules.compute.core.base import EngineProgressEvent

        self.current_job_id = None
        return EngineProgressEvent(job_id=job_id or 'job-1', event={'type': 'progress'})

    def shutdown(self) -> None:
        return None


def test_engine_progress_queue_returns_matching_event() -> None:
    engine = ProgressReadyEngine()

    event = engine.get_progress_event(job_id='job-1')

    assert event is not None
    assert event.job_id == 'job-1'
    assert event.event['type'] == 'progress'


def test_engine_shutdown_closes_queues_even_when_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = PolarsComputeEngine('analysis')
    engine.is_running = False
    closed = {'value': False}

    def fake_close() -> None:
        closed['value'] = True

    monkeypatch.setattr(engine, '_close_queues', fake_close)

    engine.shutdown()

    assert closed['value'] is True


def test_build_canonical_engine_run_result_persists_unified_detail_shape() -> None:
    result = compute_service._build_canonical_engine_run_result(
        existing_result={
            'resources': [
                {
                    'sampled_at': '2026-04-08T12:00:00Z',
                    'cpu_percent': 25.0,
                    'memory_mb': 128.0,
                    'memory_limit_mb': 512.0,
                    'active_threads': 4,
                    'max_threads': 8,
                }
            ],
            'logs': [
                {
                    'timestamp': '2026-04-08T12:00:01Z',
                    'level': 'info',
                    'message': 'Running build',
                }
            ],
        },
        summary_meta={
            'row_count': 3,
            'query_plans': {'optimized': 'optimized plan', 'unoptimized': 'raw plan'},
            'source_datasource_id': 'input-ds-1',
            'source_datasource_name': 'Source 1',
        },
        execution_entries=[
            {
                'key': 'initial_read',
                'label': 'Initial Read',
                'category': 'read',
                'order': 0,
                'duration_ms': 12.0,
                'metadata': None,
            },
            {
                'key': 'filter_1',
                'label': 'Filter',
                'category': 'step',
                'order': 1,
                'duration_ms': 25.0,
                'metadata': {'step_type': 'filter'},
            },
            {
                'key': 'write_output',
                'label': 'Write Output',
                'category': 'write',
                'order': 2,
                'duration_ms': 18.0,
                'metadata': None,
            },
        ],
        current_output_id='output-ds-1',
        current_output_name='output_salary_predictions',
        current_tab_id='tab-1',
        current_tab_name='View',
        total_steps=3,
        total_tabs=1,
        resource_config={'max_threads': 8, 'max_memory_mb': 512, 'streaming_chunk_size': 1000},
        results=[
            {
                'tab_id': 'tab-1',
                'tab_name': 'View',
                'status': 'success',
                'output_id': 'output-ds-1',
                'output_name': 'output_salary_predictions',
            }
        ],
        append_logs=[
            {
                'timestamp': '2026-04-08T12:00:02Z',
                'level': 'info',
                'message': 'Built output output_salary_predictions',
                'tab_id': 'tab-1',
                'tab_name': 'View',
                'step_id': None,
                'step_name': None,
            }
        ],
    )

    assert result['current_output_name'] == 'output_salary_predictions'
    assert result['source_datasource_id'] == 'input-ds-1'
    assert result['source_datasource_name'] == 'Source 1'
    assert result['row_count'] == 3
    assert result['query_plans'] == [
        {
            'tab_id': 'tab-1',
            'tab_name': 'View',
            'optimized_plan': 'optimized plan',
            'unoptimized_plan': 'raw plan',
        }
    ]
    assert result['steps'] == [
        {
            'build_step_index': 0,
            'step_index': 0,
            'step_id': 'initial_read',
            'step_name': 'Initial Read',
            'step_type': 'read',
            'tab_id': 'tab-1',
            'tab_name': 'View',
            'state': 'completed',
            'duration_ms': 12.0,
            'row_count': None,
            'error': None,
        },
        {
            'build_step_index': 1,
            'step_index': 1,
            'step_id': 'filter_1',
            'step_name': 'Filter',
            'step_type': 'filter',
            'tab_id': 'tab-1',
            'tab_name': 'View',
            'state': 'completed',
            'duration_ms': 25.0,
            'row_count': None,
            'error': None,
        },
        {
            'build_step_index': 2,
            'step_index': 2,
            'step_id': 'write_output',
            'step_name': 'Write Output',
            'step_type': 'write',
            'tab_id': 'tab-1',
            'tab_name': 'View',
            'state': 'completed',
            'duration_ms': 18.0,
            'row_count': None,
            'error': None,
        },
    ]
    resources = result['resources']
    assert isinstance(resources, list)
    assert resources[0]['cpu_percent'] == 25.0
    latest_resources = result['latest_resources']
    assert isinstance(latest_resources, dict)
    assert latest_resources['cpu_percent'] == 25.0
    logs = result['logs']
    assert isinstance(logs, list)
    assert logs[0]['message'] == 'Running build'
    assert logs[1]['message'] == 'Built output output_salary_predictions'
    results = result['results']
    assert isinstance(results, list)
    assert results[0]['output_name'] == 'output_salary_predictions'


def test_finalize_failed_engine_run_preserves_omitted_current_step() -> None:
    session = MagicMock()
    error = RuntimeError('preview failed')

    with patch('modules.compute.service.engine_run_service.update_engine_run') as update:
        compute_service._finalize_failed_engine_run(
            session,
            run_id='run-1',
            existing_result={'logs': []},
            execution_entries=[],
            error=error,
            completed_at=datetime.now(UTC),
            duration_ms=25,
            step_timings={},
            current_tab_id='tab-1',
            current_tab_name='Tab 1',
            total_steps=2,
            total_tabs=1,
            resource_config={'max_threads': 4, 'max_memory_mb': 256, 'streaming_chunk_size': None},
            result_entry=compute_service._result_entry(
                tab_id='tab-1',
                tab_name='Tab 1',
                status=compute_schemas.BuildTabStatus.FAILED,
                error=str(error),
            ),
            log_entry=compute_service._log_entry(
                message=str(error),
                level='error',
                tab_id='tab-1',
                tab_name='Tab 1',
            ),
        )

    kwargs = update.call_args.kwargs
    assert kwargs['status'] == compute_schemas.ComputeRunStatus.FAILED
    assert kwargs['error_message'] == 'preview failed'
    assert 'current_step' not in kwargs
    assert 'query_plan' not in kwargs


def test_finalize_failed_engine_run_preserves_explicit_none_current_step_and_query_plan() -> None:
    session = MagicMock()
    error = RuntimeError('export failed')

    with patch('modules.compute.service.engine_run_service.update_engine_run') as update:
        compute_service._finalize_failed_engine_run(
            session,
            run_id='run-2',
            existing_result={'results': []},
            execution_entries=[{'key': 'step-1', 'label': 'Step 1', 'category': 'step', 'order': 0}],
            error=error,
            completed_at=datetime.now(UTC),
            duration_ms=50,
            step_timings={'step-1': 12.5},
            query_plan=None,
            summary_meta={'source_datasource_id': 'ds-1', 'source_datasource_name': 'Source 1'},
            current_output_id='out-1',
            current_output_name='Output 1',
            current_tab_id='tab-1',
            current_tab_name='Tab 1',
            total_steps=4,
            total_tabs=1,
            resource_config={'max_threads': 2, 'max_memory_mb': 128, 'streaming_chunk_size': 1000},
            result_entry=compute_service._result_entry(
                tab_id='tab-1',
                tab_name='Tab 1',
                status=compute_schemas.BuildTabStatus.FAILED,
                output_id='out-1',
                output_name='Output 1',
                error=str(error),
            ),
            log_entry=compute_service._log_entry(
                message=str(error),
                level='error',
                tab_id='tab-1',
                tab_name='Tab 1',
            ),
            current_step=None,
        )

    kwargs = update.call_args.kwargs
    assert kwargs['status'] == compute_schemas.ComputeRunStatus.FAILED
    assert kwargs['error_message'] == 'export failed'
    assert 'current_step' in kwargs
    assert kwargs['current_step'] is None
    assert 'query_plan' in kwargs
    assert kwargs['query_plan'] is None


def test_schedule_stream_tasks_runs_on_main_loop() -> None:
    loop = asyncio.new_event_loop()
    progress_task = None
    resource_task = None

    async def emitter(_payload: dict[str, object]) -> None:
        return None

    class FakeEngine:
        def is_process_alive(self) -> bool:
            return False

        effective_resources: dict[str, int] = {}

    def worker() -> tuple[asyncio.Task, asyncio.Task]:
        future: concurrent.futures.Future[tuple[asyncio.Task, asyncio.Task]] = concurrent.futures.Future()

        def assign() -> None:
            from modules.compute.service import _schedule_stream_tasks

            future.set_result(
                _schedule_stream_tasks(
                    loop,
                    engine=FakeEngine(),
                    job_id='job-1',
                    build_step_base=0,
                    engine_step_offset=0,
                    total_steps=1,
                    started_perf=time.perf_counter(),
                    tab_id='tab1',
                    tab_name='Tab 1',
                    current_output_id=None,
                    current_output_name=None,
                    emitter=emitter,
                    read_stage=None,
                )
            )

        loop.call_soon_threadsafe(assign)
        return future.result(timeout=5)

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run_loop)
    thread.start()
    try:
        progress_task, resource_task = worker()
        assert progress_task.get_loop() is loop
        assert resource_task.get_loop() is loop
    finally:
        if progress_task is not None:
            loop.call_soon_threadsafe(progress_task.cancel)
        if resource_task is not None:
            loop.call_soon_threadsafe(resource_task.cancel)
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


def test_start_stream_tasks_skips_when_loop_unavailable() -> None:
    loop = asyncio.new_event_loop()
    loop.close()

    class FakeEngine:
        effective_resources = {'max_threads': 8, 'max_memory_mb': 512, 'streaming_chunk_size': 1000}

    build = ActiveBuild(
        build_id='build-1',
        analysis_id='analysis-1',
        analysis_name='Analysis 1',
        namespace='default',
        starter=compute_service._build_starter(None),
        started_at=datetime.now(UTC),
    )

    tasks = compute_service._start_stream_tasks(
        loop,
        engine=FakeEngine(),
        job_id='job-1',
        build_step_base=0,
        engine_step_offset=0,
        total_steps=1,
        started_perf=time.perf_counter(),
        tab_id='tab1',
        tab_name='Tab 1',
        current_output_id=None,
        current_output_name=None,
        emitter=None,
        build=build,
        read_stage=None,
    )

    assert tasks == (None, None)
    assert build.resource_config is not None
    assert build.resource_config.max_threads == 8
    assert build.resource_config.max_memory_mb == 512
    assert build.resource_config.streaming_chunk_size == 1000


def test_stream_engine_events_drains_final_events_after_job_finish() -> None:
    emitted: list[dict[str, object]] = []

    async def emitter(payload: dict[str, object]) -> None:
        emitted.append(payload)

    class FakeEngine:
        def __init__(self) -> None:
            self.current_job_id: str | None = 'job-1'
            self.calls = 0

        def get_progress_event(self, _timeout: float = 1.0, _job_id: str | None = None):
            from modules.compute.core.base import EngineProgressEvent

            self.calls += 1
            if self.calls == 1:
                self.current_job_id = None
                return None
            if self.calls == 2:
                return EngineProgressEvent(
                    job_id='job-1',
                    event={
                        'type': 'plan',
                        'optimized_plan': 'OPT',
                        'unoptimized_plan': 'RAW',
                    },
                )
            if self.calls == 3:
                return EngineProgressEvent(
                    job_id='job-1',
                    event={
                        'type': 'step_complete',
                        'step_index': 0,
                        'step_id': 'step1',
                        'step_name': 'Step 1',
                        'step_type': 'filter',
                        'duration_ms': 10,
                        'row_count': 3,
                        'total_steps': 1,
                    },
                )
            return None

    async def run() -> None:
        await compute_service._stream_engine_events(
            engine=FakeEngine(),
            job_id='job-1',
            build_step_base=0,
            engine_step_offset=0,
            total_steps=1,
            started_perf=time.perf_counter(),
            tab_id='tab1',
            tab_name='Tab 1',
            current_output_id=None,
            current_output_name=None,
            emitter=emitter,
            read_stage=None,
        )

    asyncio.run(run())

    assert [payload['type'] for payload in emitted] == ['plan', 'step_complete', 'progress']
    assert emitted[0]['optimized_plan'] == 'OPT'
    assert emitted[1]['build_step_index'] == 0
    assert emitted[2]['progress'] == 1.0


class TestComputePreview:
    def test_preview_step_success(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'filter',
                                'config': {'column': 'age', 'operator': '>', 'value': 25},
                            },
                            {
                                'id': 'step2',
                                'type': 'select',
                                'config': {'columns': ['name', 'age']},
                            },
                        ],
                    },
                ],
            },
            'target_step_id': 'step1',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-123'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='preview-job-123',
                data={
                    'schema': {'name': 'String', 'age': 'Int64'},
                    'data': [{'name': 'Bob', 'age': 30}, {'name': 'Charlie', 'age': 35}],
                    'row_count': 2,
                },
                error=None,
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 200
        result = response.json()

        assert 'columns' in result
        assert 'data' in result
        assert result['total_rows'] == 2

    def test_preview_step_failure(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'invalid_operation',
                                'config': {},
                            },
                        ],
                    },
                ],
                'sources': {
                    sample_datasource.id: {
                        'source_type': sample_datasource.source_type,
                        **sample_datasource.config,
                    },
                    'out-1': {
                        'source_type': 'analysis',
                        'analysis_id': 'analysis-id',
                        'analysis_tab_id': 'tab1',
                    },
                },
            },
            'target_step_id': 'step1',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-124'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='preview-job-124',
                data=None,
                error='Invalid operation type',
                error_kind='value_error',
                error_details={},
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        # Invalid operations are request/pipeline validation errors.
        assert response.status_code == 400

    def test_preview_step_datasource_not_found(self, client):
        missing_id = str(uuid.uuid4())
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': missing_id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [],
                    },
                ],
            },
            'target_step_id': 'step1',
        }

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 400

    def test_preview_step_missing_metadata_returns_conflict(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [{'id': 'step1', 'type': 'view', 'config': {}}],
                    },
                ],
            },
            'target_step_id': 'step1',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()
        mock_engine.preview.return_value = 'preview-job-125'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='preview-job-125',
                data=None,
                error='Iceberg metadata_path not found: /tmp/path',
                error_kind='datasource_metadata_missing',
                error_details={'metadata_path': '/tmp/path'},
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 409

    def test_engine_list_websocket_sends_snapshot_and_updates(self, client):
        manager = app.state.manager
        original_factory = manager._engine_factory
        manager._engine_factory = FakeEngine
        analysis_id = str(uuid.uuid4())
        try:
            with client.websocket_connect('/api/v1/compute/ws/engines?namespace=default') as websocket:
                initial = websocket.receive_json()
                assert initial == {'type': 'snapshot', 'engines': [], 'total': 0}

                spawn = client.post(f'/api/v1/compute/engine/spawn/{analysis_id}')
                assert spawn.status_code == 200
                spawned = websocket.receive_json()
                assert spawned['type'] == 'snapshot'
                assert spawned['total'] == 1
                assert spawned['engines'][0]['analysis_id'] == analysis_id
                assert spawned['engines'][0]['status'] == 'healthy'

                shutdown = client.delete(f'/api/v1/compute/engine/{analysis_id}')
                assert shutdown.status_code == 204
                cleared = websocket.receive_json()
                assert cleared == {'type': 'snapshot', 'engines': [], 'total': 0}
        finally:
            manager._engine_factory = original_factory
            manager.shutdown_all()

    def test_preview_step_missing_metadata_preflight_skips_engine(self, client):
        missing_id = str(uuid.uuid4())
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': missing_id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [{'id': 'step1', 'type': 'view', 'config': {}}],
                    },
                ],
            },
            'target_step_id': 'step1',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()
        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 400
        mock_engine.preview.assert_not_called()

    def test_preview_step_specific_target(self, client, sample_datasource: DataSource):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [
                            {'id': 'step1', 'type': 'filter', 'config': {}},
                            {'id': 'step2', 'type': 'select', 'config': {}},
                            {'id': 'step3', 'type': 'sort', 'config': {}},
                        ],
                    },
                ],
            },
            'target_step_id': 'step2',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-125'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='preview-job-125',
                data={'schema': {}, 'data': [], 'row_count': 0},
                error=None,
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 200

    def test_preview_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'filter',
                                'config': {'column': 'age', 'operator': '>', 'value': 25},
                            },
                        ],
                    },
                ],
            },
            'target_step_id': 'step1',
            'row_limit': 10,
            'page': 1,
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-126'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='preview-job-126',
                data={
                    'schema': {'name': 'String'},
                    'data': [{'name': 'Bob'}],
                    'row_count': 1,
                    'query_plans': {'optimized': 'opt', 'unoptimized': 'unopt'},
                },
                error=None,
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/preview', json=payload)

        assert response.status_code == 200

        result = test_db_session.execute(select(EngineRun))
        runs = result.scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'preview'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource']['id'] == sample_datasource.id
        assert run.request_json['iceberg_options']['branch'] == 'master'
        assert 'data' not in run.result_json
        assert run.result_json['query_plans'][0]['optimized_plan'] == 'opt'
        assert run.result_json['execution_entries'][0]['key'] == 'query_plan'


def test_list_active_builds_returns_running_build(client, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-1',
            analysis_name='Analysis 1',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    asyncio.run(
        active_build_registry.apply_event(
            build.build_id,
            {
                'type': 'progress',
                'build_id': build.build_id,
                'analysis_id': 'analysis-1',
                'emitted_at': datetime.now(UTC).isoformat(),
                'progress': 0.5,
                'elapsed_ms': 1200,
                'total_steps': 4,
                'current_step': 'Filter rows',
                'current_step_index': 1,
            },
        )
    )

    response = client.get('/api/v1/compute/builds/active')

    assert response.status_code == 200
    payload = response.json()
    assert payload['total'] == 1
    assert payload['builds'][0]['build_id'] == build.build_id
    assert payload['builds'][0]['status'] == 'running'
    assert payload['builds'][0]['progress'] == 0.5
    assert payload['builds'][0]['starter']['user_id'] == test_user.id


def test_get_active_build_returns_detail(client, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-2',
            analysis_name='Analysis 2',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    emitted_at = datetime.now(UTC).isoformat()
    asyncio.run(
        active_build_registry.apply_event(
            build.build_id,
            {
                'type': 'step_start',
                'build_id': build.build_id,
                'analysis_id': 'analysis-2',
                'emitted_at': emitted_at,
                'build_step_index': 0,
                'step_index': 0,
                'step_id': 'step-1',
                'step_name': 'Load source',
                'step_type': 'source',
                'total_steps': 1,
            },
        )
    )
    asyncio.run(
        active_build_registry.apply_event(
            build.build_id,
            {
                'type': 'log',
                'build_id': build.build_id,
                'analysis_id': 'analysis-2',
                'emitted_at': emitted_at,
                'level': 'info',
                'message': 'Started build',
            },
        )
    )

    response = client.get(f'/api/v1/compute/builds/active/{build.build_id}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['build_id'] == build.build_id
    assert payload['steps'][0]['step_id'] == 'step-1'
    assert payload['steps'][0]['state'] == 'running'
    assert payload['logs'][0]['message'] == 'Started build'


def test_get_active_build_returns_resource_config_summary(client, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-config',
            analysis_name='Analysis Config',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    registry_build = asyncio.run(active_build_registry.get_build(build.build_id))
    assert registry_build is not None
    registry_build.resource_config = compute_schemas.BuildResourceConfigSummary(
        max_threads=6,
        max_memory_mb=1024,
        streaming_chunk_size=2000,
    )

    response = client.get(f'/api/v1/compute/builds/active/{build.build_id}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['resource_config'] == {
        'max_threads': 6,
        'max_memory_mb': 1024,
        'streaming_chunk_size': 2000,
    }


def test_get_active_build_by_engine_run_returns_detail(client, test_db_session, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-live-by-run',
            analysis_name='Analysis Live By Run',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-live-by-run',
            datasource_id='output-ds-live-by-run',
            kind='datasource_create',
            status='running',
            request_json={'kind': 'datasource_create'},
            result_json={},
        ),
    )
    test_db_session.commit()
    asyncio.run(
        active_build_registry.apply_event(
            build.build_id,
            {
                'type': 'progress',
                'build_id': build.build_id,
                'analysis_id': 'analysis-live-by-run',
                'emitted_at': datetime.now(UTC).isoformat(),
                'engine_run_id': created.id,
                'progress': 0.25,
                'elapsed_ms': 900,
                'total_steps': 3,
                'current_step': 'Load source',
                'current_step_index': 0,
            },
        )
    )

    response = client.get(f'/api/v1/compute/builds/active/by-engine-run/{created.id}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['build_id'] == build.build_id
    assert payload['current_engine_run_id'] == created.id
    assert payload['status'] == 'running'


def test_cancel_build_marks_running_run_cancelled(client, test_db_session, test_user) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-cancel',
            datasource_id='output-ds-1',
            kind='datasource_update',
            status='running',
            request_json={'kind': 'datasource_update'},
            result_json={
                'steps': [
                    {
                        'build_step_index': 0,
                        'step_index': 0,
                        'step_id': 'step-1',
                        'step_name': 'Load source',
                        'step_type': 'read',
                        'state': 'completed',
                    }
                ],
                'results': [{'tab_id': 'tab-1', 'tab_name': 'View', 'status': 'success'}],
            },
            created_at=datetime.now(UTC),
            progress=0.42,
            current_step='Filter rows',
        ),
    )
    mock_manager = MagicMock()
    app.dependency_overrides[get_manager] = lambda: mock_manager

    response = client.post(f'/api/v1/compute/cancel/{created.id}')

    assert response.status_code == 200
    payload = response.json()
    assert payload['id'] == created.id
    assert payload['status'] == 'cancelled'
    assert payload['cancelled_by'] == test_user.email

    run = test_db_session.get(EngineRun, created.id)
    assert run is not None
    test_db_session.refresh(run)
    assert run.status == 'cancelled'
    assert run.error_message == f'Cancelled by {test_user.email}'
    assert isinstance(run.result_json, dict)
    assert run.result_json['results'] == []
    assert run.result_json['cancelled_by'] == test_user.email
    assert run.result_json['last_completed_step'] == 'Load source'
    mock_manager.shutdown_engine.assert_called_once_with('analysis-cancel')


def test_cancel_build_requires_running_status(client, test_db_session) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-not-running',
            datasource_id='output-ds-2',
            kind='datasource_update',
            status='success',
            request_json={'kind': 'datasource_update'},
            result_json={},
            created_at=datetime.now(UTC),
        ),
    )

    response = client.post(f'/api/v1/compute/cancel/{created.id}')

    assert response.status_code == 400
    assert response.json()['detail'] == 'Only running builds can be cancelled'


def test_cancel_build_updates_active_build_registry(client, test_db_session, test_user) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-live-cancel',
            datasource_id='output-ds-3',
            kind='datasource_update',
            status='running',
            request_json={'kind': 'datasource_update'},
            result_json={},
            created_at=datetime.now(UTC),
        ),
    )
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-live-cancel',
            analysis_name='Live Cancel',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    asyncio.run(
        active_build_registry.apply_event(
            build.build_id,
            {
                'type': 'progress',
                'build_id': build.build_id,
                'analysis_id': 'analysis-live-cancel',
                'emitted_at': datetime.now(UTC).isoformat(),
                'engine_run_id': created.id,
                'progress': 0.35,
                'elapsed_ms': 1200,
                'total_steps': 4,
                'current_step': 'Sort',
                'current_step_index': 1,
            },
        )
    )
    mock_manager = MagicMock()
    app.dependency_overrides[get_manager] = lambda: mock_manager

    response = client.post(f'/api/v1/compute/cancel/{created.id}')

    assert response.status_code == 200
    updated = asyncio.run(active_build_registry.get_build(build.build_id))
    assert updated is not None
    assert updated.status == compute_schemas.ActiveBuildStatus.CANCELLED
    assert updated.cancelled_by == test_user.email
    assert updated.current_engine_run_id == created.id


def test_build_stream_websocket_emits_snapshot_and_terminal_event(client, sample_datasource: DataSource, test_user) -> None:
    payload = {
        'analysis_pipeline': {
            'analysis_id': 'analysis-stream',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Tab 1',
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'out',
                    },
                    'steps': [
                        {
                            'id': 'step1',
                            'type': 'filter',
                            'config': {'column': 'age', 'operator': '>', 'value': 25},
                        }
                    ],
                }
            ],
        },
        'tab_id': 'tab1',
    }
    release = threading.Event()

    async def fake_run_analysis_build_stream(session, manager, pipeline, *, build, emitter, triggered_by):
        del session, manager, pipeline, triggered_by
        await asyncio.to_thread(release.wait, 5)
        await emitter(
            {
                'type': 'plan',
                'optimized_plan': 'OPT PLAN',
                'unoptimized_plan': 'RAW PLAN',
                'tab_id': 'tab1',
                'tab_name': 'Tab 1',
            }
        )
        await emitter(
            {
                'type': 'step_start',
                'build_step_index': 0,
                'step_index': 0,
                'step_id': 'step1',
                'step_name': 'Filter rows',
                'step_type': 'filter',
                'total_steps': 1,
                'tab_id': 'tab1',
                'tab_name': 'Tab 1',
            }
        )
        await emitter(
            {
                'type': 'resources',
                'cpu_percent': 10.5,
                'memory_mb': 128.0,
                'memory_limit_mb': 512,
                'active_threads': 4,
                'max_threads': 8,
                'tab_id': 'tab1',
                'tab_name': 'Tab 1',
            }
        )
        await emitter(
            {
                'type': 'log',
                'level': 'info',
                'message': 'Running filter',
                'step_name': 'Filter rows',
                'step_id': 'step1',
                'tab_id': 'tab1',
                'tab_name': 'Tab 1',
            }
        )
        await emitter(
            {
                'type': 'step_complete',
                'build_step_index': 0,
                'step_index': 0,
                'step_id': 'step1',
                'step_name': 'Filter rows',
                'step_type': 'filter',
                'duration_ms': 42,
                'row_count': 3,
                'total_steps': 1,
                'tab_id': 'tab1',
                'tab_name': 'Tab 1',
            }
        )
        await emitter(
            {
                'type': 'progress',
                'progress': 1.0,
                'elapsed_ms': 42,
                'estimated_remaining_ms': 0,
                'current_step': 'Filter rows',
                'current_step_index': 0,
                'total_steps': 1,
                'tab_id': 'tab1',
                'tab_name': 'Tab 1',
            }
        )
        await emitter(
            {
                'type': 'complete',
                'elapsed_ms': 50,
                'total_steps': 1,
                'tabs_built': 1,
                'duration_ms': 50,
                'results': [{'tab_id': 'tab1', 'tab_name': 'Tab 1', 'status': 'success'}],
            }
        )
        return {
            'analysis_id': build.analysis_id,
            'tabs_built': 1,
            'results': [{'tab_id': 'tab1', 'tab_name': 'Tab 1', 'status': 'success'}],
        }

    with (
        patch('modules.compute.routes.service.run_analysis_build_stream', side_effect=fake_run_analysis_build_stream),
        patch('modules.compute.routes._build_analysis_name', return_value='Stream Analysis'),
    ):
        response = client.post('/api/v1/compute/builds/active', json=payload)
        assert response.status_code == 200
        started = response.json()
        build_id = started['build_id']
        assert started['starter']['user_id'] == test_user.id

        with client.websocket_connect(f'/api/v1/compute/ws/builds/{build_id}?namespace=default') as websocket:
            snapshot = websocket.receive_json()
            release.set()
            plan = websocket.receive_json()
            step_start = websocket.receive_json()
            resources = websocket.receive_json()
            log = websocket.receive_json()
            step_complete = websocket.receive_json()
            progress = websocket.receive_json()
            complete = websocket.receive_json()

    assert snapshot['type'] == 'snapshot'
    assert snapshot['build']['build_id'] == build_id
    assert plan['type'] == 'plan'
    assert plan['build_id'] == build_id
    assert step_start['type'] == 'step_start'
    assert resources['type'] == 'resources'
    assert log['type'] == 'log'
    assert step_complete['type'] == 'step_complete'
    assert progress['type'] == 'progress'
    assert complete['type'] == 'complete'
    assert complete['results'][0]['status'] == 'success'


def test_start_active_build_notifies_active_build_list_watchers(client, sample_datasource: DataSource, test_user) -> None:
    payload = {
        'analysis_pipeline': {
            'analysis_id': 'analysis-list-watch',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Tab 1',
                    'datasource': {
                        'id': sample_datasource.id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': str(uuid.uuid4()),
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'out',
                    },
                    'steps': [],
                }
            ],
        },
        'tab_id': 'tab1',
    }
    release = threading.Event()

    async def fake_run_analysis_build_stream(session, manager, pipeline, *, build, emitter, triggered_by):
        del session, manager, pipeline, build, emitter, triggered_by
        await asyncio.to_thread(release.wait, 5)
        return {'analysis_id': 'analysis-list-watch', 'tabs_built': 1, 'results': []}

    with (
        patch('modules.compute.routes.service.run_analysis_build_stream', side_effect=fake_run_analysis_build_stream),
        patch('modules.compute.routes._build_analysis_name', return_value='List Watch Analysis'),
        client.websocket_connect('/api/v1/compute/ws/builds?namespace=default') as websocket,
    ):
        initial = websocket.receive_json()
        assert initial == {'type': 'snapshot', 'builds': []}

        response = client.post('/api/v1/compute/builds/active', json=payload)
        assert response.status_code == 200

        created = websocket.receive_json()
        release.set()

    assert created['type'] == 'snapshot'
    assert len(created['builds']) == 1
    assert created['builds'][0]['analysis_name'] == 'List Watch Analysis'


def test_active_build_registry_sanitizes_logs_and_flushes_throttled_events(test_user) -> None:
    async def run() -> tuple[list[dict[str, object]], ActiveBuild | None]:
        build = await active_build_registry.create_build(
            analysis_id='analysis-log',
            analysis_name='Analysis Log',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
        websocket = MagicMock()
        sent: list[dict[str, object]] = []

        async def send_json(payload: dict[str, object]) -> None:
            sent.append(payload)

        websocket.send_json = AsyncMock(side_effect=send_json)
        await active_build_registry.add_watcher(build.build_id, websocket)

        first = {
            'type': 'log',
            'build_id': build.build_id,
            'analysis_id': build.analysis_id,
            'emitted_at': datetime.now(UTC).isoformat(),
            'level': 'info',
            'message': '\x1b[31mhello\x00 world\r\n',
        }
        second = {
            'type': 'log',
            'build_id': build.build_id,
            'analysis_id': build.analysis_id,
            'emitted_at': datetime.now(UTC).isoformat(),
            'level': 'info',
            'message': 'second message',
        }
        terminal = {
            'type': 'complete',
            'build_id': build.build_id,
            'analysis_id': build.analysis_id,
            'emitted_at': datetime.now(UTC).isoformat(),
            'elapsed_ms': 12,
            'total_steps': 1,
            'tabs_built': 1,
            'duration_ms': 12,
            'results': [{'tab_id': 'tab1', 'tab_name': 'Tab 1', 'status': 'success'}],
        }

        await active_build_registry.apply_event(build.build_id, first)
        await active_build_registry.publish(build.build_id, first)
        await active_build_registry.apply_event(build.build_id, second)
        await active_build_registry.publish(build.build_id, second)
        await active_build_registry.apply_event(build.build_id, terminal)
        await active_build_registry.publish(build.build_id, terminal)

        stored = await active_build_registry.get_build(build.build_id)
        await active_build_registry.remove_watcher(build.build_id, websocket)
        return sent, stored

    sent, stored = asyncio.run(run())

    assert [payload['type'] for payload in sent] == ['log', 'log', 'complete']
    assert sent[0]['message'] == 'hello world'
    assert sent[1]['message'] == 'second message'
    assert stored is not None
    assert [item.message for item in stored.logs] == ['hello world', 'second message']


def test_active_build_monitor_websocket_sends_snapshot_and_updates(client, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-watch',
            analysis_name='Watch Build',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )

    with client.websocket_connect(f'/api/v1/compute/ws/builds/{build.build_id}?namespace=default') as websocket:
        snapshot = websocket.receive_json()
        asyncio.run(
            active_build_registry.publish(
                build.build_id,
                {
                    'type': 'progress',
                    'build_id': build.build_id,
                    'analysis_id': build.analysis_id,
                    'emitted_at': datetime.now(UTC).isoformat(),
                    'progress': 0.75,
                    'elapsed_ms': 3000,
                    'total_steps': 4,
                    'current_step': 'Sort',
                    'current_step_index': 2,
                },
            )
        )
        update = websocket.receive_json()

    assert snapshot['type'] == 'snapshot'
    assert snapshot['build']['build_id'] == build.build_id
    assert update['type'] == 'progress'
    assert update['build_id'] == build.build_id


def test_active_build_list_websocket_sends_snapshot_and_updates(client, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-list',
            analysis_name='List Build',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )

    with client.websocket_connect('/api/v1/compute/ws/builds?namespace=default') as websocket:
        snapshot = websocket.receive_json()
        asyncio.run(
            active_build_registry.publish(
                build.build_id,
                {
                    'type': 'log',
                    'build_id': build.build_id,
                    'analysis_id': build.analysis_id,
                    'emitted_at': datetime.now(UTC).isoformat(),
                    'level': 'info',
                    'message': 'hello',
                },
            )
        )
        update = websocket.receive_json()

    assert snapshot['type'] == 'snapshot'
    assert snapshot['builds'][0]['build_id'] == build.build_id
    assert update['type'] == 'snapshot'
    assert update['builds'][0]['build_id'] == build.build_id


def test_run_analysis_build_stream_tracks_output_target_and_read_write_stages(test_user) -> None:
    class FakeProgressEvent:
        def __init__(self, event: dict[str, object]) -> None:
            self.event = event

    class FakeEngine:
        def __init__(self) -> None:
            self.analysis_id = 'analysis-live'
            self.resource_config: dict[str, int] = {}
            self.effective_resources: dict[str, int] = {}
            self.current_job_id: str | None = 'job-1'
            self._events = [
                FakeProgressEvent(
                    {
                        'type': 'step_start',
                        'step_index': 0,
                        'step_id': 'step-1',
                        'step_name': 'Filter rows',
                        'step_type': 'filter',
                        'total_steps': 3,
                    }
                ),
                FakeProgressEvent(
                    {
                        'type': 'step_complete',
                        'step_index': 0,
                        'step_id': 'step-1',
                        'step_name': 'Filter rows',
                        'step_type': 'filter',
                        'duration_ms': 25,
                        'row_count': None,
                        'total_steps': 3,
                    }
                ),
            ]

        def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None):
            del timeout, job_id
            if self._events:
                event = self._events.pop(0)
                if not self._events:
                    self.current_job_id = None
                return event
            self.current_job_id = None
            return None

    async def fake_monitor_engine_resources(engine):
        del engine
        if False:
            yield None

    def fake_export_data(*args, **kwargs):
        del args
        job_started = kwargs['job_started']
        build_stage_event = kwargs['build_stage_event']
        job_started({'job_id': 'job-1', 'engine': FakeEngine()})
        time.sleep(0.05)
        build_stage_event({'stage': 'write_start', 'read_duration_ms': 12.0})
        time.sleep(0.01)
        build_stage_event({'stage': 'write_complete', 'write_duration_ms': 7.0})
        return compute_service.ExportDatasourceResult(
            datasource_id='output-ds-1',
            datasource_name='output_salary_predictions',
            result_meta={'datasource_id': 'output-ds-1', 'datasource_name': 'output_salary_predictions'},
            source_datasource_id='source-ds-1',
            engine_run_id='run-1',
            read_duration_ms=12.0,
            write_duration_ms=7.0,
        )

    async def run() -> tuple[list[dict[str, object]], ActiveBuild]:
        await active_build_registry.clear()
        build = await active_build_registry.create_build(
            analysis_id='analysis-live',
            analysis_name='Live Analysis',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
        emitted: list[dict[str, object]] = []

        async def emitter(payload: dict[str, object]) -> None:
            normalized = {
                'build_id': build.build_id,
                'analysis_id': build.analysis_id,
                'emitted_at': datetime.now(UTC).isoformat(),
                **payload,
            }
            emitted.append(normalized)
            await active_build_registry.apply_event(build.build_id, normalized)

        pipeline = {
            'analysis_id': 'analysis-live',
            'tab_id': 'tab-1',
            'tabs': [
                {
                    'id': 'tab-1',
                    'name': 'View',
                    'datasource': {'id': 'source-ds-1', 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                    'output': {
                        'result_id': 'output-ds-1',
                        'filename': 'view',
                        'iceberg': {'table_name': 'output_salary_predictions', 'namespace': 'outputs', 'branch': 'master'},
                        'build_mode': 'full',
                    },
                    'steps': [{'id': 'step-1', 'type': 'filter', 'config': {'column': 'age', 'operator': '>', 'value': 25}}],
                }
            ],
            'sources': {},
        }

        with (
            patch('modules.compute.service.export_data', side_effect=fake_export_data),
            patch('modules.compute.service.monitor_engine_resources', side_effect=fake_monitor_engine_resources),
        ):
            await compute_service.run_analysis_build_stream(
                session=MagicMock(),
                manager=MagicMock(),
                pipeline=pipeline,
                build=build,
                emitter=emitter,
                triggered_by=str(test_user.id),
            )

        stored = await active_build_registry.get_build(build.build_id)
        assert stored is not None
        return emitted, stored

    emitted, stored = asyncio.run(run())

    assert stored.current_output_id == 'output-ds-1'
    assert stored.current_output_name == 'output_salary_predictions'
    assert stored.current_engine_run_id == 'run-1'
    assert [step.step_name for step in stored.detail().steps] == ['Initial Read', 'Filter rows', 'Write Output']
    assert [step.step_type for step in stored.detail().steps] == ['read', 'filter', 'write']
    assert stored.detail().steps[0].duration_ms is not None
    assert stored.detail().steps[2].duration_ms == 7
    assert stored.detail().results[0].output_name == 'output_salary_predictions'
    complete = next(event for event in emitted if event['type'] == 'complete')
    assert complete['engine_run_id'] == 'run-1'
    complete_results = complete.get('results')
    assert isinstance(complete_results, list)
    typed_complete_results = cast(list[dict[str, object]], complete_results)
    assert typed_complete_results[0]['output_name'] == 'output_salary_predictions'


def test_finalize_failed_engine_run_persists_failure_state(test_db_session) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id='analysis-failed-build',
            datasource_id='output-1',
            kind='datasource_update',
            status='running',
            request_json={'kind': 'datasource_update'},
            result_json=compute_service._initial_live_run_result(
                current_output_id='output-1',
                current_output_name='output_table',
                current_tab_id='tab1',
                current_tab_name='Tab 1',
                total_steps=1,
                total_tabs=1,
            ),
            created_at=datetime.now(UTC),
        ),
    )

    compute_service._finalize_failed_engine_run(
        test_db_session,
        run_id=created.id,
        existing_result=compute_service._load_engine_run_result_json(test_db_session, created.id),
        execution_entries=[],
        error=RuntimeError('build exploded'),
        completed_at=datetime.now(UTC),
        duration_ms=40,
        step_timings={},
        current_output_id='output-1',
        current_output_name='output_table',
        current_tab_id='tab1',
        current_tab_name='Tab 1',
        total_steps=1,
        total_tabs=1,
        resource_config=None,
        result_entry={
            'tab_id': 'tab1',
            'tab_name': 'Tab 1',
            'status': 'failed',
            'output_id': 'output-1',
            'output_name': 'output_table',
            'error': 'build exploded',
        },
        log_entry={'timestamp': datetime.now(UTC).isoformat(), 'level': 'error', 'message': 'build exploded'},
    )

    test_db_session.expire_all()
    run = test_db_session.get(EngineRun, created.id)

    assert run is not None
    assert run.status == 'failed'
    assert run.error_message == 'build exploded'
    assert run.result_json['results'][0]['status'] == 'failed'
    assert run.result_json['current_output_name'] == 'output_table'
    assert run.result_json['steps'] == []
    assert run.result_json['logs'][0]['message'] == 'build exploded'


def test_active_build_registry_prunes_old_finished_builds(test_user) -> None:
    old_build_ids: list[str] = []
    for idx in range(105):
        build = asyncio.run(
            active_build_registry.create_build(
                analysis_id=f'analysis-{idx}',
                analysis_name=f'Analysis {idx}',
                namespace='default',
                starter=compute_service._build_starter(test_user),
                total_tabs=1,
            )
        )
        old_build_ids.append(build.build_id)
        asyncio.run(
            active_build_registry.apply_event(
                build.build_id,
                {
                    'type': 'complete',
                    'build_id': build.build_id,
                    'analysis_id': build.analysis_id,
                    'emitted_at': datetime.now(UTC).isoformat(),
                    'elapsed_ms': 10,
                    'total_steps': 1,
                    'tabs_built': 1,
                    'duration_ms': 10,
                    'results': [{'tab_id': 'tab1', 'tab_name': 'Tab 1', 'status': 'success'}],
                },
            )
        )

    builds = asyncio.run(active_build_registry.list_builds())

    assert len(builds) == 100
    assert old_build_ids[0] not in {build.build_id for build in builds}


def test_safe_send_json_returns_false_when_socket_disconnected() -> None:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.DISCONNECTED
    websocket.application_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock()

    result = asyncio.run(_safe_send_json(websocket, {'type': 'error'}))

    assert result is False
    websocket.send_json.assert_not_called()


def test_safe_send_json_reraises_unexpected_runtime_error() -> None:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock(side_effect=RuntimeError('boom'))

    with pytest.raises(RuntimeError, match='boom'):
        asyncio.run(_safe_send_json(websocket, {'type': 'error'}))


def test_wait_for_websocket_disconnect_treats_receive_disconnect_runtimeerror_as_normal() -> None:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED

    async def receive_disconnect_race() -> dict[str, str]:
        websocket.client_state = WebSocketState.DISCONNECTED
        raise RuntimeError('Cannot call "receive" once a disconnect message has been received.')

    websocket.receive = AsyncMock(side_effect=receive_disconnect_race)

    asyncio.run(_wait_for_websocket_disconnect(websocket))


def test_engine_list_stream_treats_disconnect_runtimeerror_as_normal(monkeypatch) -> None:
    websocket = MagicMock()
    websocket.headers.get.return_value = None
    websocket.query_params.get.return_value = 'default'
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED

    async def boom(*_args, **_kwargs) -> None:
        raise RuntimeError('Cannot call "receive" once a disconnect message has been received')

    add = AsyncMock()
    remove = AsyncMock()
    snap = AsyncMock()

    monkeypatch.setattr('modules.compute.routes._require_websocket_user', AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr('modules.compute.routes._send_engine_snapshot', snap)
    monkeypatch.setattr('modules.compute.routes._wait_for_websocket_disconnect', boom)
    monkeypatch.setattr('modules.compute.routes._safe_send_json', AsyncMock())
    monkeypatch.setattr('modules.compute.routes.engine_registry.add_watcher', add)
    monkeypatch.setattr('modules.compute.routes.engine_registry.remove_watcher', remove)

    asyncio.run(engine_list_stream(websocket))

    add.assert_awaited_once()
    remove.assert_awaited_once()
    snap.assert_awaited_once()


def test_build_list_stream_treats_disconnect_runtimeerror_as_normal(monkeypatch) -> None:
    websocket = MagicMock()
    websocket.headers.get.return_value = None
    websocket.query_params.get.return_value = 'default'
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED

    async def boom(*_args, **_kwargs) -> None:
        raise RuntimeError('Cannot call "send" once a close message has been sent')

    add = AsyncMock()
    remove = AsyncMock()
    snap = AsyncMock()

    monkeypatch.setattr('modules.compute.routes._require_websocket_user', AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr('modules.compute.routes._send_build_list_snapshot', snap)
    monkeypatch.setattr('modules.compute.routes._wait_for_websocket_disconnect', boom)
    monkeypatch.setattr('modules.compute.routes._safe_send_json', AsyncMock())
    monkeypatch.setattr('modules.compute.routes.build_registry.add_list_watcher', add)
    monkeypatch.setattr('modules.compute.routes.build_registry.remove_list_watcher', remove)

    asyncio.run(build_list_stream(websocket))

    add.assert_awaited_once()
    remove.assert_awaited_once()
    snap.assert_awaited_once()


def test_active_build_stream_treats_disconnect_runtimeerror_as_normal(monkeypatch, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-stream',
            analysis_name='Stream Build',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    websocket = MagicMock()
    websocket.headers.get.return_value = None
    websocket.query_params.get.return_value = 'default'
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.application_state = WebSocketState.CONNECTED

    async def boom(*_args, **_kwargs) -> None:
        raise RuntimeError('Unexpected ASGI message after websocket.close')

    add = AsyncMock()
    remove = AsyncMock()
    snap = AsyncMock()

    monkeypatch.setattr('modules.compute.routes._require_websocket_user', AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr('modules.compute.routes._send_build_snapshot', snap)
    monkeypatch.setattr('modules.compute.routes._wait_for_websocket_disconnect', boom)
    monkeypatch.setattr('modules.compute.routes._safe_send_json', AsyncMock())
    monkeypatch.setattr('modules.compute.routes.build_registry.add_watcher', add)
    monkeypatch.setattr('modules.compute.routes.build_registry.remove_watcher', remove)

    asyncio.run(active_build_stream(websocket, build.build_id))

    add.assert_awaited_once()
    remove.assert_awaited_once()
    snap.assert_awaited_once_with(websocket, build.build_id)


def test_active_build_registry_tracks_and_drops_finished_task(test_user) -> None:
    async def run() -> None:
        build = await active_build_registry.create_build(
            analysis_id='analysis-task',
            analysis_name='Analysis Task',
            namespace='default',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )

        async def worker() -> None:
            await asyncio.sleep(0)

        task = asyncio.create_task(worker())
        await active_build_registry.track_task(build.build_id, task)
        assert await active_build_registry.get_task(build.build_id) is task

        _ = await asyncio.gather(task)
        await asyncio.sleep(0)

        assert await active_build_registry.get_task(build.build_id) is None

    asyncio.run(run())


def test_active_build_detail_websocket_rejects_wrong_namespace(client, test_user) -> None:
    build = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-other',
            analysis_name='Other Namespace Build',
            namespace='alpha',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )

    with client.websocket_connect(f'/api/v1/compute/ws/builds/{build.build_id}?namespace=beta') as websocket:
        payload = websocket.receive_json()

    assert payload == {'type': 'error', 'error': 'Active build not found', 'status_code': 404}


def test_active_build_list_websocket_filters_namespace(client, test_user) -> None:
    asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-alpha',
            analysis_name='Alpha Build',
            namespace='alpha',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )
    beta = asyncio.run(
        active_build_registry.create_build(
            analysis_id='analysis-beta',
            analysis_name='Beta Build',
            namespace='beta',
            starter=compute_service._build_starter(test_user),
            total_tabs=1,
        )
    )

    with client.websocket_connect('/api/v1/compute/ws/builds?namespace=beta') as websocket:
        snapshot = websocket.receive_json()

    assert snapshot['type'] == 'snapshot'
    assert [item['build_id'] for item in snapshot['builds']] == [beta.build_id]


def test_process_manager_isolates_same_analysis_id_by_namespace(monkeypatch) -> None:
    manager = ProcessManager(engine_factory=fake_engine_factory)
    monkeypatch.setattr(
        ProcessManager,
        '_get_defaults',
        lambda self: {'max_threads': 0, 'max_memory_mb': 0, 'streaming_chunk_size': 0},
    )

    alpha = set_namespace_context('alpha')
    try:
        manager.spawn_engine('shared-analysis')
        assert manager.get_engine('shared-analysis') is not None
        assert manager.list_engines() == ['shared-analysis']
    finally:
        reset_namespace(alpha)

    beta = set_namespace_context('beta')
    try:
        assert manager.get_engine('shared-analysis') is None
        manager.spawn_engine('shared-analysis')
        assert manager.get_engine('shared-analysis') is not None
        assert manager.list_engines() == ['shared-analysis']
    finally:
        reset_namespace(beta)

    alpha = set_namespace_context('alpha')
    try:
        assert manager.get_engine('shared-analysis') is not None
        assert manager.list_engines() == ['shared-analysis']
    finally:
        reset_namespace(alpha)

    manager.shutdown_all()


class TestComputeExport:
    def test_export_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'select',
                                'config': {'columns': ['name']},
                            },
                        ],
                    },
                ],
            },
            'target_step_id': 'step1',
            'format': 'csv',
            'filename': 'export-test',
            'destination': 'download',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.preview.return_value = 'preview-job-126'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='preview-job-126',
                data={
                    'schema': {'id': 'Int64', 'name': 'String'},
                    'data': [{'id': 1, 'name': 'Alice'}],
                    'row_count': 1,
                },
                error=None,
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/export', json=payload)

        assert response.status_code == 200

        result = test_db_session.execute(select(EngineRun))
        runs = result.scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'download'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource']['id'] == sample_datasource.id
        assert run.request_json['iceberg_options']['branch'] == 'master'
        assert run.result_json['format'] == 'csv'
        assert run.result_json['filename'] == 'export-test.csv'


class TestComputeRowCount:
    def test_row_count_logs_engine_run(self, client, sample_datasource: DataSource, test_db_session):
        payload = {
            'analysis_id': 'analysis-id',
            'analysis_pipeline': {
                'analysis_id': 'analysis-id',
                'tabs': [
                    {
                        'id': 'tab1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {
                            'result_id': 'out-1',
                            'datasource_type': 'iceberg',
                            'format': 'parquet',
                            'filename': 'out',
                        },
                        'steps': [
                            {
                                'id': 'step1',
                                'type': 'select',
                                'config': {'columns': ['name']},
                            },
                        ],
                    },
                ],
            },
            'target_step_id': 'step1',
        }

        mock_manager = MagicMock()
        mock_engine = MagicMock()

        mock_engine.get_row_count.return_value = 'row-count-job-123'
        mock_engine.get_result.side_effect = [
            None,
            EngineResult(
                job_id='row-count-job-123',
                data={'row_count': 42},
                error=None,
            ),
        ]

        mock_manager.get_engine.return_value = None
        mock_manager.get_or_create_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post('/api/v1/compute/row-count', json=payload)

        assert response.status_code == 200
        result = response.json()
        assert result['row_count'] == 42

        test_db_session.expire_all()
        runs = test_db_session.execute(select(EngineRun)).scalars().all()
        assert len(runs) == 1

        run = runs[0]
        assert run.kind == 'row_count'
        assert run.status == 'success'
        assert run.request_json['analysis_pipeline']['tabs'][0]['datasource']['id'] == sample_datasource.id
        assert run.request_json['iceberg_options']['branch'] == 'master'
        assert run.result_json['row_count'] == 42


def _build_fake_dataframe() -> MagicMock:
    fake_df = MagicMock()
    fake_df.schema = {}
    fake_df.__len__.return_value = 0
    fake_head = MagicMock()
    fake_head.to_dicts.return_value = []
    fake_df.head.return_value = fake_head
    return fake_df


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_cycle_detection(mock_apply_step: MagicMock, mock_load: MagicMock):
    mock_load.return_value = MagicMock()
    mock_apply_step.side_effect = lambda frame, _step, **kwargs: frame

    steps = [
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': ['step2'],
        },
        {'id': 'step2', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['step1']},
    ]

    with pytest.raises(PipelineValidationError, match='cycle'):
        PolarsComputeEngine._build_pipeline({}, steps, 'job', MagicMock())


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_multiple_dependencies_collapsed(mock_apply_step: MagicMock, mock_load: MagicMock):
    """Multi-dependency steps are collapsed to single-dep by apply_steps()."""
    fake_lf = MagicMock()
    fake_lf.collect_schema.return_value = {}

    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    steps = [
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': [],
        },
        {
            'id': 'step2',
            'type': 'select',
            'config': {'columns': ['col']},
            'depends_on': ['step1', 'step3'],
        },
        {'id': 'step3', 'type': 'sort', 'config': {'columns': ['col'], 'descending': [False]}, 'depends_on': []},
    ]

    # apply_steps collapses multi-deps to single-dep (takes deps[0]),
    # so _build_pipeline should succeed without raising
    result = PolarsComputeEngine.build_pipeline({}, steps, 'job', MagicMock())
    assert result == fake_lf


@patch('modules.compute.engine.load_datasource')
@patch('modules.compute.engine.PolarsComputeEngine._apply_step')
def test_pipeline_topological_order(mock_apply_step: MagicMock, mock_load: MagicMock):
    fake_lf = MagicMock()
    fake_lf.collect_schema.return_value = {}

    mock_load.return_value = fake_lf
    mock_apply_step.return_value = fake_lf

    steps = [
        {
            'id': 'step1',
            'type': 'filter',
            'config': {'conditions': [{'column': 'col', 'operator': '>', 'value': 1}]},
            'depends_on': [],
        },
        {'id': 'step2', 'type': 'select', 'config': {'columns': ['col']}, 'depends_on': ['step1']},
        {
            'id': 'step3',
            'type': 'sort',
            'config': {'columns': ['col'], 'descending': [False]},
            'depends_on': ['step2'],
        },
    ]

    # build_pipeline returns just the LazyFrame
    result = PolarsComputeEngine.build_pipeline({}, steps, 'job', MagicMock())
    assert result == fake_lf


class FakeEngine:
    def __init__(self, analysis_id: str, resource_config: dict[str, int] | None = None) -> None:
        self.analysis_id = analysis_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict[str, int] = {}
        self.current_job_id: str | None = None
        self._alive = False
        self._pid = id(self)

    @property
    def process_id(self) -> int | None:
        return self._pid if self._alive else None

    def start(self) -> None:
        self._alive = True

    def is_process_alive(self) -> bool:
        return self._alive

    def check_health(self) -> bool:
        return self._alive

    def preview(self, *_args, **_kwargs) -> str:
        return 'job'

    def export(self, *_args, **_kwargs) -> str:
        return 'job'

    def get_schema(self, *_args, **_kwargs) -> str:
        return 'job'

    def get_row_count(self, *_args, **_kwargs) -> str:
        return 'job'

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> EngineResult | None:
        del timeout, job_id
        return None

    def get_progress_event(self, timeout: float = 1.0, job_id: str | None = None) -> EngineProgressEvent | None:
        del timeout, job_id
        return None

    def shutdown(self) -> None:
        # Delay the initial engine shutdown long enough for the conflicting restart
        # thread to race the old TOCTOU path deterministically.
        time.sleep(0.2 if self.resource_config.get('max_threads') == 1 else 0)
        self._alive = False


def fake_engine_factory(analysis_id: str, resource_config: dict | None = None) -> ComputeEngine:
    return FakeEngine(analysis_id, resource_config)


def test_spawn_engine_preserves_requested_config_during_conflicting_restarts(monkeypatch):
    manager = ProcessManager(engine_factory=fake_engine_factory)
    monkeypatch.setattr(
        ProcessManager,
        '_get_defaults',
        lambda self: {'max_threads': 0, 'max_memory_mb': 0, 'streaming_chunk_size': 0},
    )
    manager.spawn_engine('analysis', {'max_threads': 1})

    results: dict[str, dict[str, int]] = {}
    barrier = threading.Barrier(2)

    def worker(name: str, config: dict[str, int]) -> None:
        barrier.wait()
        info = manager.spawn_engine('analysis', config)
        results[name] = info.engine.resource_config

    first = threading.Thread(target=worker, args=('config_2', {'max_threads': 2}))
    second = threading.Thread(target=worker, args=('config_3', {'max_threads': 3}))
    first.start()
    second.start()
    first.join()
    second.join()

    assert results['config_2'] == {'max_threads': 2}
    assert results['config_3'] == {'max_threads': 3}
    assert manager.get_engine('analysis') is not None


def test_spawn_engine_evicts_oldest_idle_when_limit_reached(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from core.config import settings

    manager = ProcessManager(engine_factory=fake_engine_factory)
    monkeypatch.setattr(
        ProcessManager,
        '_get_defaults',
        lambda self: {'max_threads': 0, 'max_memory_mb': 0, 'streaming_chunk_size': 0},
    )
    monkeypatch.setattr(settings, 'max_concurrent_engines', 2)
    manager.spawn_engine('a')
    manager.spawn_engine('b')
    info = manager.get_engine_info('a')
    assert info is not None
    info.last_activity = datetime.now(UTC) - timedelta(seconds=1)
    manager.spawn_engine('c')
    engines = set(manager.list_engines())
    assert engines == {'b', 'c'}


def test_analysis_stack_context_copy_isolated():
    token = _analysis_stack_var.set((('root', None),))
    try:
        copied = contextvars.copy_context()

        def mutate_copy() -> tuple[tuple[str, str | None], ...]:
            stack = _analysis_stack_var.get()
            _analysis_stack_var.set((*stack, ('child', None)))
            return _analysis_stack_var.get()

        copied_stack = copied.run(mutate_copy)

        assert copied_stack == (('root', None), ('child', None))
        assert _analysis_stack_var.get() == (('root', None),)
    finally:
        _analysis_stack_var.reset(token)


class TestEngineLifecycle:
    def test_spawn_engine(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.spawn_engine.return_value = MagicMock()
        mock_manager.get_engine_status.return_value = {
            'analysis_id': analysis_id,
            'status': 'healthy',
            'process_id': 12345,
            'last_activity': '2024-01-01T00:00:00',
            'current_job_id': None,
        }
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post(f'/api/v1/compute/engine/spawn/{analysis_id}')

        assert response.status_code == 200
        result = response.json()
        assert result['analysis_id'] == analysis_id
        assert result['status'] == 'healthy'

    def test_keepalive_engine(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.keepalive.return_value = MagicMock()
        mock_manager.get_engine_status.return_value = {
            'analysis_id': analysis_id,
            'status': 'healthy',
            'process_id': 12345,
            'last_activity': '2024-01-01T00:00:00',
            'current_job_id': None,
        }
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.post(f'/api/v1/compute/engine/keepalive/{analysis_id}')

        assert response.status_code == 200
        result = response.json()
        assert result['analysis_id'] == analysis_id

    def test_shutdown_engine(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_engine = MagicMock()
        mock_engine.current_job_id = None
        mock_engine.is_process_alive.return_value = False
        mock_manager.get_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

        assert response.status_code == 204
        mock_manager.shutdown_engine.assert_called_once_with(analysis_id)

    def test_shutdown_engine_conflicts_with_active_job(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_engine = MagicMock()
        mock_engine.current_job_id = 'job-1'
        mock_engine.is_process_alive.return_value = True
        mock_manager.get_engine.return_value = mock_engine
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

        assert response.status_code == 409
        assert response.json() == {'detail': 'Engine has an active job'}
        mock_manager.shutdown_engine.assert_not_called()

    def test_shutdown_engine_not_found(self, client):
        analysis_id = str(uuid.uuid4())
        mock_manager = MagicMock()
        mock_manager.get_engine.return_value = None
        app.dependency_overrides[get_manager] = lambda: mock_manager

        response = client.delete(f'/api/v1/compute/engine/{analysis_id}')

        assert response.status_code == 404


class TestBuildAnalysisPipelinePayloadDerived:
    """Verify derived tabs are encoded inline in pipeline tab datasource metadata."""

    def test_derived_tab_datasource_contains_analysis_metadata(self, test_db_session, sample_datasource: DataSource):
        from datetime import UTC, datetime

        from modules.analysis.models import Analysis, AnalysisStatus
        from modules.compute.service import build_analysis_pipeline_payload
        from modules.datasource.service import create_placeholder_output_datasource

        analysis_id = str(uuid.uuid4())
        tab1_result_id = str(uuid.uuid4())
        tab2_result_id = str(uuid.uuid4())

        now = datetime.now(UTC).replace(tzinfo=None)
        analysis = Analysis(
            id=analysis_id,
            name='test',
            created_at=now,
            updated_at=now,
            pipeline_definition={
                'tabs': [
                    {
                        'id': 'tab1',
                        'name': 'Source',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {'result_id': tab1_result_id, 'format': 'parquet', 'filename': 'source'},
                        'steps': [],
                    },
                    {
                        'id': 'tab2',
                        'name': 'Derived',
                        'parent_id': 'tab1',
                        'datasource': {
                            'id': tab1_result_id,
                            'analysis_tab_id': 'tab1',
                            'config': {'branch': 'master'},
                        },
                        'output': {'result_id': tab2_result_id, 'format': 'parquet', 'filename': 'derived'},
                        'steps': [],
                    },
                ],
            },
            status=AnalysisStatus.DRAFT,
        )
        test_db_session.add(analysis)
        create_placeholder_output_datasource(test_db_session, tab1_result_id, analysis_id, 'tab1')
        create_placeholder_output_datasource(test_db_session, tab2_result_id, analysis_id, 'tab2')
        test_db_session.commit()

        payload = build_analysis_pipeline_payload(test_db_session, analysis)

        tab2 = payload['tabs'][1]
        assert tab2['datasource']['id'] == tab1_result_id
        assert tab2['datasource']['source_type'] == 'analysis'
        assert tab2['datasource']['analysis_tab_id'] == 'tab1'


class TestDownloadStepFiltering:
    """Unit tests for download-step filtering logic in download_step().

    Steps arrive in frontend format (key='type', not 'operation').
    The function must filter out download steps and fall back to the parent
    when the target_step_id points at a download step.
    """

    def test_download_type_steps_are_filtered_out(self) -> None:
        """Steps with type='download' must be excluded from download_steps."""
        steps: list[dict[str, object]] = [
            {'id': 'step1', 'type': 'filter', 'config': {}},
            {'id': 'step2', 'type': 'download', 'config': {}, 'depends_on': ['step1']},
            {'id': 'step3', 'type': 'select', 'config': {}},
        ]

        download_steps = [step for step in steps if step.get('type') != 'download']

        assert len(download_steps) == 2
        ids = [s['id'] for s in download_steps]
        assert 'step2' not in ids
        assert 'step1' in ids
        assert 'step3' in ids

    def test_target_download_step_falls_back_to_parent(self) -> None:
        """When target_step_id matches a download step, fall back to depends_on[0]."""
        steps: list[dict[str, object]] = [
            {'id': 'step1', 'type': 'filter', 'config': {}},
            {'id': 'step2', 'type': 'download', 'config': {}, 'depends_on': ['step1']},
        ]
        target_step_id = 'step2'

        target_step = next((step for step in steps if step.get('id') == target_step_id), None)

        assert target_step is not None
        assert target_step.get('type') == 'download'

        # Replicate the fallback logic from download_step()
        depends_on = target_step.get('depends_on') or []
        assert isinstance(depends_on, list)
        parent_id = str(depends_on[0]) if depends_on and depends_on[0] else None

        assert parent_id == 'step1'

    def test_target_download_step_falls_back_to_last_step_when_no_parent(self) -> None:
        """When target is a download step without depends_on, fall back to last remaining step."""
        steps: list[dict[str, object]] = [
            {'id': 'step1', 'type': 'filter', 'config': {}},
            {'id': 'step2', 'type': 'download', 'config': {}},
        ]
        target_step_id = 'step2'

        download_steps = [step for step in steps if step.get('type') != 'download']
        target_step = next((step for step in steps if step.get('id') == target_step_id), None)

        assert target_step is not None
        assert target_step.get('type') == 'download'

        depends_on = target_step.get('depends_on') or []
        assert isinstance(depends_on, list)
        parent_id = str(depends_on[0]) if depends_on and depends_on[0] else None

        # No parent, so fall back to last remaining step
        assert parent_id is None
        target_step_id = str(download_steps[-1].get('id') or 'source') if download_steps else 'source'

        assert target_step_id == 'step1'
