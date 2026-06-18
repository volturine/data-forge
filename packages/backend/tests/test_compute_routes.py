from sqlalchemy import select

from backend_core import engine_runs_service as engine_run_service
from backend_core.contracts.datasource.models import DataSourceCreatedBy
from backend_core.contracts.datasource.source_types import DataSourceType
from backend_core.contracts.engine_runs.schemas import EngineRunKind, EngineRunStatus
from backend_core.dependencies import get_manager, get_runtime_availability_probe
from backend_core.namespace import reset_namespace, set_namespace_context
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from main import app
from modules.compute import routes as compute_routes


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
        return f'{identity.scope}:{compute_routes._engine_identity_resource_id(identity)}'

    def get_engine(self, identity):
        return _StubEngine() if self._identity_key(identity).endswith(':build-1') else None

    def get_engine_status(self, identity) -> dict[str, object]:
        return {
            'analysis_id': identity.analysis_id if identity.HasField('analysis_id') else '',
            'resource_id': compute_routes._engine_identity_resource_id(identity),
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


def test_shutdown_engine_returns_not_found_for_unknown_identity(client) -> None:
    manager = _StubManager()
    app.dependency_overrides[get_manager] = lambda: manager
    try:
        response = client.delete('/api/v1/compute/engine/build/missing')
    finally:
        app.dependency_overrides.pop(get_manager, None)

    assert response.status_code == 404
    assert manager.shutdown_calls == []


def test_get_engine_defaults_resolves_auto_values(client, monkeypatch) -> None:
    monkeypatch.setattr(compute_routes.settings, 'polars_max_threads', 0)
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
    app.dependency_overrides[get_runtime_availability_probe] = lambda: _AvailableRuntimeProbe()
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
    assert test_db_session.execute(select(BuildJob).where(BuildJob.build_id == build_id)).scalars().first() is not None
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
