import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import WebSocket
from sqlalchemy import select

from backend_core import (
    compute_worker_runs_service as compute_worker_run_service,
    database,
    datasource_delete_service,
    websocket as websocket_core,
)
from backend_core.api_execution_budget import (
    ApiWorkAdmissionFull,
    install_api_blocking_executor,
    remove_api_blocking_executor,
)
from backend_core.domain.compute import schemas as compute_schemas
from backend_core.domain.compute_worker_runs.schemas import ComputeWorkerRunKind, ComputeWorkerRunStatus
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.exceptions import AppError
from backend_core.namespace import get_namespace, reset_namespace, set_namespace_context
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.persistence.build_runs.models import BuildRun
from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.runtime_events.models import RuntimeOutboxEvent, RuntimeOutboxStatus
from backend_core.sqlmodel_typing import sa
from dataforge_protocol import compute_pb2, enums_pb2
from modules.compute import executor_client, routes as compute_routes


def _make_test_websocket(sent, receive) -> WebSocket:
    async def send(message):
        sent.append(message)

    return WebSocket(
        {
            'type': 'websocket',
            'asgi': {'version': '3.0', 'spec_version': '2.3'},
            'http_version': '1.1',
            'scheme': 'ws',
            'server': ('test', 80),
            'client': ('test', 1234),
            'root_path': '',
            'path': '/ws',
            'raw_path': b'/ws',
            'query_string': b'',
            'headers': [],
            'subprotocols': [],
            'state': {},
            'extensions': {},
        },
        receive,
        send,
    )


@pytest.mark.asyncio
async def test_engine_websocket_reports_auth_overload_without_reusing_thread_pool(monkeypatch) -> None:
    submissions = []

    async def reject_auth_submission(function, *args, **kwargs):
        submissions.append((function, args, kwargs))
        raise ApiWorkAdmissionFull()

    monkeypatch.setattr(compute_routes, 'run_api_blocking', reject_auth_submission)

    async def receive():
        return {'type': 'websocket.connect'}

    sent: list[dict[str, Any]] = []
    websocket = _make_test_websocket(sent, receive)
    await compute_routes.compute_workers_stream(websocket)

    assert len(submissions) == 1
    assert [message['type'] for message in sent] == ['websocket.accept', 'websocket.send', 'websocket.close']
    assert json.loads(sent[1]['text']) == {
        'type': 'error',
        'error': 'API execution capacity is full',
        'status_code': 503,
    }


@pytest.mark.asyncio
async def test_websocket_error_send_after_close_is_a_noop() -> None:
    sent: list[dict[str, Any]] = []

    async def receive():
        return {'type': 'websocket.connect'}

    websocket = _make_test_websocket(sent, receive)

    await websocket.accept()
    await websocket_core.safe_close_websocket(websocket)
    result = await websocket_core.safe_send_json_error(websocket, {'error': 'late error'})

    assert result is False
    assert [message['type'] for message in sent] == ['websocket.accept', 'websocket.close']


@pytest.mark.asyncio
async def test_websocket_close_after_client_disconnect_is_a_noop() -> None:
    sent: list[dict[str, Any]] = []

    async def receive():
        return {'type': 'websocket.connect'} if not sent else {'type': 'websocket.disconnect', 'code': 1000}

    websocket = _make_test_websocket(sent, receive)

    await websocket.accept()
    await websocket.receive()
    result = await websocket_core.safe_send_json_error(websocket, {'error': 'late error'})
    await websocket_core.safe_close_websocket(websocket)

    assert result is False
    assert [message['type'] for message in sent] == ['websocket.accept']


@pytest.mark.asyncio
async def test_websocket_auth_uses_the_bounded_api_executor(monkeypatch) -> None:
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    auth_threads: list[int] = []
    user = cast(Any, object())
    executor = ThreadPoolExecutor(max_workers=1)
    install_api_blocking_executor(loop, executor, workers=1, max_pending=0)

    def resolve_user(_websocket):
        auth_threads.append(threading.get_ident())
        return user

    monkeypatch.setattr(compute_routes, '_resolve_websocket_user', resolve_user)

    try:
        resolved = await compute_routes._require_websocket_user(cast(Any, object()))
    finally:
        remove_api_blocking_executor(loop)
        executor.shutdown(wait=True)

    assert resolved is user
    assert len(auth_threads) == 1
    assert auth_threads[0] != loop_thread


def test_compute_response_read_scopes_namespace_for_database_session(monkeypatch) -> None:
    read_ids: list[str] = []
    result = object()

    def run_db(function, request_id: str):
        assert function is executor_client._read_request
        assert get_namespace() == 'tenant-a'
        read_ids.append(request_id)
        return result

    monkeypatch.setattr(executor_client, 'run_db', run_db)
    caller_namespace = set_namespace_context('caller')
    try:
        response = executor_client._read_request_in_new_session('request-1', 'tenant-a')
        assert get_namespace() == 'caller'
    finally:
        reset_namespace(caller_namespace)

    assert response is result
    assert read_ids == ['request-1']


@pytest.mark.asyncio
async def test_engine_shutdown_creates_uses_and_closes_session_in_its_db_thread(monkeypatch) -> None:
    loop_thread = threading.get_ident()
    operations: list[tuple[str, int, str]] = []

    class OwnedSession:
        def __init__(self, _engine):
            self.owner = threading.get_ident()
            operations.append(('create', self.owner, get_namespace()))

        def __enter__(self):
            return self

        def __exit__(self, *_error):
            assert threading.get_ident() == self.owner
            operations.append(('close', threading.get_ident(), get_namespace()))

    def request_shutdown(session, *, identity):
        assert threading.get_ident() == session.owner
        assert identity.resource_id == 'analysis-1'
        operations.append(('queue', threading.get_ident(), get_namespace()))

    monkeypatch.setattr(database, 'Session', OwnedSession)
    monkeypatch.setattr(database, '_get_tenant_engine', object)
    monkeypatch.setattr(executor_client, 'request_compute_worker_shutdown', request_shutdown)
    namespace_token = set_namespace_context('shutdown-test')
    try:
        await compute_routes._shutdown_compute_worker_identity(
            compute_pb2.ComputeWorkerIdentity(resource_id='analysis-1'),
        )
    finally:
        reset_namespace(namespace_token)

    assert [name for name, _, _ in operations] == ['create', 'queue', 'close']
    assert all(thread != loop_thread and namespace == 'shutdown-test' for _, thread, namespace in operations)


def test_validated_compute_request_stages_on_one_thread(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    sentinel = object()

    def validate(session, pipeline) -> None:
        del session, pipeline
        calls.append(('validate', threading.get_ident()))

    def submit(session, **kwargs):
        del session
        kwargs['validate']()
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
        del session
        kwargs['validate']()
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
    )

    assert calls == ['datasource-1:True', 'datasource-2:True', 'submit']


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


def _status_for_identity(identity: compute_pb2.ComputeWorkerIdentity) -> compute_schemas.ComputeWorkerStatusSchema:
    if identity.HasField('datasource_id'):
        scope = compute_schemas.ComputeWorkerScope.DATASOURCE_PREVIEW
        reuse_policy = compute_schemas.ComputeWorkerReusePolicy.SHARED
        datasource_id = identity.datasource_id
        analysis_id = None
        build_id = None
    elif identity.HasField('build_id'):
        scope = compute_schemas.ComputeWorkerScope.BUILD
        reuse_policy = compute_schemas.ComputeWorkerReusePolicy.EXCLUSIVE
        datasource_id = None
        analysis_id = None
        build_id = identity.build_id
    else:
        scope = compute_schemas.ComputeWorkerScope.ANALYSIS_INTERACTIVE
        reuse_policy = compute_schemas.ComputeWorkerReusePolicy.SHARED
        datasource_id = None
        analysis_id = identity.analysis_id
        build_id = None
    return compute_schemas.ComputeWorkerStatusSchema(
        analysis_id=analysis_id,
        resource_id=identity.resource_id,
        status=compute_schemas.ComputeWorkerStatus.HEALTHY,
        scope=scope,
        reuse_policy=reuse_policy,
        datasource_id=datasource_id,
        build_id=build_id,
    )


def test_spawn_compute_worker_queues_datasource_preview_identity(client, monkeypatch) -> None:
    calls: list[tuple[compute_pb2.ComputeWorkerIdentity, dict[str, object] | None]] = []

    async def spawn(*, identity, resource_config):
        calls.append((identity, resource_config))
        return _status_for_identity(identity)

    monkeypatch.setattr(executor_client, 'spawn_compute_worker', spawn)
    response = client.post('/api/v1/compute/compute-worker/spawn/datasource-preview/datasource-1')

    assert response.status_code == 200
    assert response.json()['status'] == 'healthy'
    assert response.json()['analysis_id'] is None
    assert response.json()['resource_id'] == 'datasource-1'
    assert response.json()['scope'] == 'datasource_preview'
    assert response.json()['reuse_policy'] == 'shared'
    assert response.json()['datasource_id'] == 'datasource-1'
    assert len(calls) == 1
    identity, resource_config = calls[0]
    assert identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW
    assert identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED
    assert identity.datasource_id == identity.resource_id == 'datasource-1'
    assert resource_config is None


def test_spawn_compute_worker_queues_analysis_identity(client, monkeypatch) -> None:
    calls: list[tuple[compute_pb2.ComputeWorkerIdentity, dict[str, object] | None]] = []

    async def spawn(*, identity, resource_config):
        calls.append((identity, resource_config))
        return _status_for_identity(identity)

    monkeypatch.setattr(executor_client, 'spawn_compute_worker', spawn)
    response = client.post('/api/v1/compute/compute-worker/spawn/analysis/analysis-1')

    assert response.status_code == 200
    assert response.json()['status'] == 'healthy'
    assert response.json()['analysis_id'] == 'analysis-1'
    assert response.json()['resource_id'] == 'analysis-1'
    assert response.json()['scope'] == 'analysis_interactive'
    assert response.json()['reuse_policy'] == 'shared'
    identity, resource_config = calls[0]
    assert identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE
    assert identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED
    assert identity.analysis_id == identity.resource_id == 'analysis-1'
    assert resource_config is None


def test_legacy_engine_lifecycle_route_is_removed(client) -> None:
    response = client.post('/api/v1/compute/engine/spawn/analysis/analysis-1')

    assert response.status_code in {404, 405}


def test_configure_compute_worker_queues_datasource_identity_and_resource_config(client, monkeypatch) -> None:
    calls: list[tuple[compute_pb2.ComputeWorkerIdentity, dict[str, object]]] = []

    async def configure(*, identity, resource_config):
        calls.append((identity, resource_config))
        return _status_for_identity(identity)

    monkeypatch.setattr(executor_client, 'configure_compute_worker', configure)
    response = client.post(
        '/api/v1/compute/compute-worker/configure/datasource-preview/datasource-1',
        json={'max_threads': 4},
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'healthy'
    assert response.json()['resource_id'] == 'datasource-1'
    assert response.json()['scope'] == 'datasource_preview'
    identity, resource_config = calls[0]
    assert identity.scope == enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW
    assert identity.reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED
    assert identity.datasource_id == identity.resource_id == 'datasource-1'
    assert resource_config == {'max_threads': 4, 'max_memory_mb': None, 'streaming_chunk_size': None}


@pytest.mark.parametrize(
    ('path', 'scope', 'reuse_policy', 'identity_field', 'resource_id'),
    [
        (
            '/api/v1/compute/compute-worker/analysis/analysis-1',
            enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
            enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            'analysis_id',
            'analysis-1',
        ),
        (
            '/api/v1/compute/compute-worker/datasource-preview/datasource-1',
            enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW,
            enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
            'datasource_id',
            'datasource-1',
        ),
        (
            '/api/v1/compute/compute-worker/build/build-1',
            enums_pb2.COMPUTE_WORKER_SCOPE_BUILD,
            enums_pb2.COMPUTE_WORKER_REUSE_POLICY_EXCLUSIVE,
            'build_id',
            'build-1',
        ),
    ],
)
def test_shutdown_compute_worker_queues_exact_identity(
    client,
    monkeypatch,
    path: str,
    scope: int,
    reuse_policy: int,
    identity_field: str,
    resource_id: str,
) -> None:
    shutdown_calls: list[compute_pb2.ComputeWorkerIdentity] = []

    def request_shutdown(session, *, identity) -> None:
        del session
        shutdown_calls.append(identity)

    monkeypatch.setattr(executor_client, 'request_compute_worker_shutdown', request_shutdown)
    response = client.delete(path)

    assert response.status_code == 204
    assert len(shutdown_calls) == 1
    identity = shutdown_calls[0]
    assert identity.scope == scope
    assert identity.reuse_policy == reuse_policy
    assert identity.resource_id == getattr(identity, identity_field) == resource_id


def test_shutdown_compute_worker_queues_unregistered_build_identity(client, monkeypatch) -> None:
    shutdown_calls: list[compute_pb2.ComputeWorkerIdentity] = []

    def request_shutdown(session, *, identity) -> None:
        del session
        shutdown_calls.append(identity)

    monkeypatch.setattr(executor_client, 'request_compute_worker_shutdown', request_shutdown)
    response = client.delete('/api/v1/compute/compute-worker/build/missing')

    assert response.status_code == 204
    assert len(shutdown_calls) == 1
    assert shutdown_calls[0].build_id == shutdown_calls[0].resource_id == 'missing'


def test_shutdown_compute_worker_queues_worker_shutdown_without_waiting(client, monkeypatch) -> None:
    shutdown_calls: list[compute_pb2.ComputeWorkerIdentity] = []

    def request_shutdown(session, *, identity) -> None:
        del session
        shutdown_calls.append(identity)

    monkeypatch.setattr(executor_client, 'request_compute_worker_shutdown', request_shutdown)

    response = client.delete('/api/v1/compute/compute-worker/build/build-1')

    assert response.status_code == 204
    assert len(shutdown_calls) == 1
    assert shutdown_calls[0].build_id == 'build-1'


def test_get_compute_worker_defaults_resolves_auto_values(client, monkeypatch) -> None:
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


def test_start_build_recreates_deleted_output_placeholder(client, test_db_session, monkeypatch) -> None:
    api_loop_threads: list[int] = []
    notification_threads: list[int] = []
    notify_calls: list[str] = []
    run_api_blocking = compute_routes.run_api_blocking

    def notify_build_job(namespace: str) -> None:
        notify_calls.append(namespace)
        notification_threads.append(threading.get_ident())

    async def track_api_blocking(function, *args, **kwargs):
        api_loop_threads.append(threading.get_ident())
        return await run_api_blocking(function, *args, **kwargs)

    monkeypatch.setattr(compute_routes.runtime_ipc, 'notify_build_job', notify_build_job)
    monkeypatch.setattr(compute_routes, 'run_api_blocking', track_api_blocking)
    test_db_session.add(
        DataSource(
            id='source-1',
            name='External build source',
            source_type=DataSourceType.FILE.value,
            config={'file_path': 's3://default/uploads/source-1.csv', 'file_type': 'csv'},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
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
    assert [row.status for row in outbox_rows] == [RuntimeOutboxStatus.PENDING, RuntimeOutboxStatus.PENDING]
    assert notify_calls == ['default']
    assert notification_threads[0] != api_loop_threads[0]


def test_list_builds_includes_preview_compute_worker_runs(client, test_db_session) -> None:
    created = compute_worker_run_service.create_compute_worker_run(
        test_db_session,
        compute_worker_run_service.create_compute_worker_run_payload(
            analysis_id=None,
            datasource_id='datasource-1',
            kind=ComputeWorkerRunKind.PREVIEW,
            status=ComputeWorkerRunStatus.SUCCESS,
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


def test_get_build_returns_preview_compute_worker_run_detail(client, test_db_session) -> None:
    created = compute_worker_run_service.create_compute_worker_run(
        test_db_session,
        compute_worker_run_service.create_compute_worker_run_payload(
            analysis_id=None,
            datasource_id='datasource-1',
            kind=ComputeWorkerRunKind.PREVIEW,
            status=ComputeWorkerRunStatus.SUCCESS,
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


def test_list_builds_excludes_compute_worker_runs_from_other_namespaces(client, test_db_session) -> None:
    token = set_namespace_context('other')
    try:
        compute_worker_run_service.create_compute_worker_run(
            test_db_session,
            compute_worker_run_service.create_compute_worker_run_payload(
                analysis_id=None,
                datasource_id='datasource-1',
                kind=ComputeWorkerRunKind.PREVIEW,
                status=ComputeWorkerRunStatus.SUCCESS,
                request_json={'target_step_id': 'source'},
            ),
        )
    finally:
        reset_namespace(token)

    response = client.get('/api/v1/compute/builds?datasource_id=datasource-1&kind=preview')

    assert response.status_code == 200
    assert response.json() == {'builds': [], 'total': 0}
