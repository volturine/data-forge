import asyncio
import threading
from typing import Any
from unittest.mock import Mock, call

import pytest
from sqlalchemy import select

from backend_core import datasource_delete_service, dependencies, engine_runs_service as engine_run_service
from backend_core.dependencies import get_manager, get_runtime_availability_probe
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.domain.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.domain.runtime_workers.models import RuntimeWorkerKind
from backend_core.exceptions import AppError
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.sqlmodel_typing import sa
from dataforge_protocol import compute_pb2
from main import app
from modules.compute import executor_client, routes as compute_routes


def test_terminal_compute_request_releases_session_connection() -> None:
    session = Mock()
    request = object()

    executor_client._detach_and_release_request(session, request)

    assert session.method_calls == [
        call.expunge(request),
        call.rollback(),
    ]


def test_validated_compute_request_stages_on_one_thread(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    sentinel = object()

    def validate(session, pipeline) -> None:
        del session, pipeline
        calls.append(('validate', threading.get_ident()))

    def submit(session, **kwargs):
        del session, kwargs
        calls.append(('submit', threading.get_ident()))
        return sentinel

    monkeypatch.setattr(executor_client, '_require_active_pipeline_datasources', validate)
    monkeypatch.setattr(executor_client, '_submit', submit)
    stub: Any = object()

    result = asyncio.run(
        asyncio.to_thread(
            executor_client._stage_validated_request,
            stub,
            pipeline=stub,
            datasource_ids=(),
            kind=stub,
            command=stub,
            runtime_probe=stub,
        )
    )

    assert result is sentinel
    assert [name for name, _ in calls] == ['validate', 'submit']
    assert calls[0][1] == calls[1][1]


def test_validated_direct_datasource_request_checks_deletion_fence(monkeypatch) -> None:
    calls: list[str] = []

    def validate(session, datasource_id, *, for_update):
        del session
        calls.append(f'{datasource_id}:{for_update}')

    def submit(session, **kwargs):
        del session, kwargs
        calls.append('submit')
        return object()

    monkeypatch.setattr(datasource_delete_service, 'get_active_datasource', validate)
    monkeypatch.setattr(executor_client, '_submit', submit)
    stub: Any = object()

    executor_client._stage_validated_request(
        stub,
        pipeline=None,
        datasource_ids=('datasource-2', 'datasource-1', 'datasource-1'),
        kind=stub,
        command=stub,
        runtime_probe=stub,
    )

    assert calls == ['datasource-1:True', 'datasource-2:True', 'submit']


class _StubEngine:
    current_job_id = None

    @staticmethod
    def is_process_alive() -> bool:
        return False


class _StubManager:
    def __init__(self) -> None:
        self.shutdown_calls: list[str] = []
        self.spawn_calls: list[tuple[str, dict | None]] = []
        self.restart_calls: list[tuple[str, dict]] = []

    @staticmethod
    def _identity_key(identity) -> str:
        return f'{identity.scope}:{identity.resource_id}'

    def get_engine(self, identity):
        return _StubEngine() if self._identity_key(identity).endswith(':build-1') else None

    def get_engine_status(self, identity) -> dict[str, object]:
        return {
            'analysis_id': identity.analysis_id if identity.HasField('analysis_id') else '',
            'resource_id': identity.resource_id,
            'status': 'healthy',
            'scope': 'datasource_preview' if identity.HasField('datasource_id') else 'build' if identity.HasField('build_id') else 'analysis_interactive',
            'reuse_policy': 'exclusive' if identity.HasField('build_id') else 'shared',
            'datasource_id': identity.datasource_id if identity.HasField('datasource_id') else None,
            'build_id': identity.build_id if identity.HasField('build_id') else None,
        }

    def spawn_engine(self, identity, resource_config: dict | None = None) -> None:
        self.spawn_calls.append((self._identity_key(identity), resource_config))

    def restart_engine_with_config(self, identity, resource_config: dict) -> None:
        self.restart_calls.append((self._identity_key(identity), resource_config))

    def shutdown_engine(self, identity) -> None:
        self.shutdown_calls.append(self._identity_key(identity))


class _AvailableRuntimeProbe:
    @staticmethod
    def available(*, kind) -> bool:
        del kind
        return True


def test_compute_queue_rejects_pipeline_after_source_delete_requested(test_db_session, sample_datasource) -> None:
    datasource_delete_service.request_delete(test_db_session, sample_datasource.id)
    request = compute_schemas.StepPreviewRequest.model_validate(
        {
            'analysis_id': 'analysis-1',
            'target_step_id': 'source',
            'analysis_pipeline': {
                'analysis_id': 'analysis-1',
                'tabs': [
                    {
                        'id': 'tab-1',
                        'datasource': {
                            'id': sample_datasource.id,
                            'analysis_tab_id': None,
                            'config': {'branch': 'master'},
                        },
                        'output': {'result_id': 'output-1', 'format': 'parquet', 'filename': 'output'},
                        'steps': [],
                    }
                ],
            },
        }
    )

    with pytest.raises(AppError, match='not found'):
        executor_client._require_active_pipeline_datasources(test_db_session, request.analysis_pipeline)


def test_persisted_runtime_availability_probe_uses_an_isolated_session_per_check(monkeypatch) -> None:
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def fake_run_settings_db(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return True

    monkeypatch.setattr(dependencies, 'run_settings_db', fake_run_settings_db)
    probe = dependencies.PersistedRuntimeAvailabilityProbe(heartbeat_seconds=7.0)

    assert probe.available(kind=RuntimeWorkerKind.BUILD_WORKER) is True
    assert probe.available(kind=RuntimeWorkerKind.SCHEDULER) is True
    assert calls == [
        (
            dependencies.runtime_workers_service.worker_available,
            (),
            {'kind': RuntimeWorkerKind.BUILD_WORKER, 'heartbeat_seconds': 7.0},
        ),
        (
            dependencies.runtime_workers_service.worker_available,
            (),
            {'kind': RuntimeWorkerKind.SCHEDULER, 'heartbeat_seconds': 7.0},
        ),
    ]


def test_spawn_engine_accepts_datasource_preview_identity(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.post('/api/v1/compute/engine/spawn/datasource-preview/datasource-1')
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 200
    assert response.json()['resource_id'] == 'datasource-1'
    assert response.json()['scope'] == 'datasource_preview'
    assert manager.spawn_calls == [('1:datasource-1', None)]


def test_configure_engine_accepts_datasource_preview_identity(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.post(
            '/api/v1/compute/engine/configure/datasource-preview/datasource-1',
            json={'max_threads': 4},
        )
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 200
    assert response.json()['resource_id'] == 'datasource-1'
    assert manager.restart_calls == [('1:datasource-1', {'max_threads': 4, 'max_memory_mb': None, 'streaming_chunk_size': None})]


def test_shutdown_engine_accepts_build_identity(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.delete('/api/v1/compute/engine/build/build-1')
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 204
    assert manager.shutdown_calls == ['3:build-1']


def test_shutdown_engine_cancels_active_job_then_shuts_down(client) -> None:
    """Busy engines cancel the job first; shutdown must not return 409."""

    class _BusyEngine:
        current_job_id = 'job-active'

        @staticmethod
        def is_process_alive() -> bool:
            return True

    class _BusyManager(_StubManager):
        def get_engine(self, identity):
            return _BusyEngine() if self._identity_key(identity).endswith(':build-1') else None

    manager = _BusyManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.delete('/api/v1/compute/engine/build/build-1')
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 204
    assert manager.shutdown_calls == ['3:build-1']


def test_shutdown_engine_returns_not_found_for_unknown_identity(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.delete('/api/v1/compute/engine/build/missing')
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 404
    assert manager.shutdown_calls == []


def test_shutdown_engine_queues_worker_shutdown_without_waiting(client, monkeypatch) -> None:
    shutdown_calls: list[compute_pb2.EngineIdentity] = []

    def request_shutdown(session, *, identity, runtime_probe) -> None:
        del session, runtime_probe
        shutdown_calls.append(identity)

    monkeypatch.setattr(executor_client, 'request_engine_shutdown', request_shutdown)

    response = client.delete('/api/v1/compute/engine/build/build-1')

    assert response.status_code == 204
    assert len(shutdown_calls) == 1
    assert shutdown_calls[0].build_id == 'build-1'


def test_get_engine_defaults_resolves_auto_values(client, monkeypatch) -> None:
    monkeypatch.setattr(compute_routes.settings, 'polars_cores_available', 0)
    monkeypatch.setattr(compute_routes.settings, 'polars_max_memory_mb', 0)
    monkeypatch.setattr(compute_routes.settings, 'polars_streaming_chunk_size', 4096)
    monkeypatch.setattr(compute_routes.os, 'cpu_count', lambda: 12)

    def fake_sysconf(name: str) -> int:
        if name == 'SC_PHYS_PAGES':
            return 2_097_152
        if name == 'SC_PAGE_SIZE':
            return 4096
        raise AssertionError(f'unexpected sysconf key: {name}')

    monkeypatch.setattr(compute_routes.os, 'sysconf', fake_sysconf)

    response = client.get('/api/v1/compute/defaults')

    assert response.status_code == 200
    assert response.json() == {
        'max_threads': 12,
        'max_memory_mb': 8192,
        'streaming_chunk_size': 4096,
    }


def test_start_build_recreates_deleted_output_placeholder(client, test_db_session) -> None:
    app.dependency_overrides[get_runtime_availability_probe] = _AvailableRuntimeProbe
    try:
        response = client.post(
            '/api/v1/compute/builds',
            json={
                'analysis_pipeline': {
                    'analysis_id': 'analysis-1',
                    'tabs': [
                        {
                            'id': 'tab-1',
                            'name': 'Source 1',
                            'datasource': {
                                'id': 'source-1',
                                'analysis_tab_id': None,
                                'source_type': 'iceberg',
                                'config': {'branch': 'master'},
                            },
                            'output': {
                                'result_id': '11111111-1111-4111-8111-111111111111',
                                'format': 'parquet',
                                'filename': 'source_1',
                                'build_mode': 'full',
                                'iceberg': {
                                    'namespace': 'outputs',
                                    'table_name': 'source_1',
                                    'branch': 'master',
                                },
                            },
                            'steps': [],
                        }
                    ],
                },
                'tab_id': 'tab-1',
            },
        )
    finally:
        app.dependency_overrides.pop(get_runtime_availability_probe, None)

    assert response.status_code == 200
    build_id = response.json()['build_id']
    datasource = test_db_session.get(DataSource, '11111111-1111-4111-8111-111111111111')
    assert datasource is not None
    assert datasource.name == 'source_1'
    assert datasource.source_type == DataSourceType.ICEBERG.value
    assert datasource.config['metadata_path'].endswith('/exports/11111111-1111-4111-8111-111111111111')
    assert datasource.config['table'] == '11111111-1111-4111-8111-111111111111_master'
    assert datasource.config['table_name'] == 'source_1'
    assert datasource.config['branch'] == 'master'
    assert datasource.config['analysis_tab_id'] == 'tab-1'
    assert datasource.created_by == DataSourceCreatedBy.ANALYSIS.value
    assert datasource.created_by_analysis_id == 'analysis-1'
    assert datasource.is_hidden is True
    assert test_db_session.get(BuildRun, build_id) is not None
    assert test_db_session.execute(select(BuildJob).where(sa(BuildJob.build_id == build_id))).scalars().first() is not None
    outbox_table = RuntimeOutboxEvent.metadata.tables[RuntimeOutboxEvent.__tablename__]
    outbox_rows = test_db_session.execute(select(RuntimeOutboxEvent).order_by(outbox_table.c.created_at)).scalars().all()
    assert [row.status for row in outbox_rows] == [RuntimeOutboxStatus.DISPATCHED, RuntimeOutboxStatus.DISPATCHED]


def test_list_builds_includes_preview_engine_runs(client, test_db_session) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id=None,
            datasource_id='datasource-1',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.SUCCESS,
            request_json={'target_step_id': 'source'},
            result_json={'row_count': 2, 'current_tab_name': 'Preview'},
            progress=1.0,
            current_step='Preview completed',
            triggered_by='test',
        ),
    )

    response = client.get('/api/v1/compute/builds?datasource_id=datasource-1&kind=preview')

    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['builds'][0]['build_id'] == created.id
    assert body['builds'][0]['current_kind'] == 'preview'
    assert body['builds'][0]['current_datasource_id'] == 'datasource-1'
    assert body['builds'][0]['status'] == 'completed'


def test_get_build_returns_preview_engine_run_detail(client, test_db_session) -> None:
    created = engine_run_service.create_engine_run(
        test_db_session,
        engine_run_service.create_engine_run_payload(
            analysis_id=None,
            datasource_id='datasource-1',
            kind=EngineRunKind.PREVIEW,
            status=EngineRunStatus.SUCCESS,
            request_json={'target_step_id': 'source'},
            result_json={'row_count': 2},
            duration_ms=123,
        ),
    )

    response = client.get(f'/api/v1/compute/builds/{created.id}')

    assert response.status_code == 200
    body = response.json()
    assert body['build_id'] == created.id
    assert body['current_kind'] == 'preview'
    assert body['duration_ms'] == 123
    assert body['request_json'] == {'target_step_id': 'source'}
    assert body['result_json'] == {'row_count': 2}


def test_list_builds_excludes_engine_runs_from_other_namespaces(client, test_db_session) -> None:
    token = set_namespace_context('other')
    try:
        engine_run_service.create_engine_run(
            test_db_session,
            engine_run_service.create_engine_run_payload(
                analysis_id=None,
                datasource_id='datasource-1',
                kind=EngineRunKind.PREVIEW,
                status=EngineRunStatus.SUCCESS,
                request_json={'target_step_id': 'source'},
            ),
        )
    finally:
        reset_namespace(token)

    response = client.get('/api/v1/compute/builds?datasource_id=datasource-1&kind=preview')

    assert response.status_code == 200
    assert response.json() == {'builds': [], 'total': 0}
