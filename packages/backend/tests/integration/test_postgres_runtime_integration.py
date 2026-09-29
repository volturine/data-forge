from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import text
from sqlmodel import Session
from websockets.asyncio.client import connect

from backend_core.migrations import _PUBLIC_REVISION, _TENANT_REVISION
from dataforge_protocol import compute_pb2, enums_pb2
from tests.harness.postgres_harness import (
    BACKEND_ROOT,
    CORE_ROOT,
    LOCAL_SERVICE_HOST,
    SCHEDULER_ROOT,
    WORKER_ROOT,
    ManagedProcess,
    PostgresContainer,
    RustfsContainer,
    docker_env,
    free_port,
    local_service_bind_address,
    require_docker,
    run_command,
    wait_for_condition,
    wait_for_http_ready,
)


def _clear_database_state() -> None:
    from backend_core import database

    if database.settings_engine is not None:
        database.settings_engine.dispose()
        database.settings_engine = None
    if database.tenant_engine is not None:
        database.tenant_engine.dispose()
        database.tenant_engine = None
    database.clear_engine_override()
    database.clear_settings_engine_override()


def _table_exists(connection: psycopg.Connection, schema: str, table: str) -> bool:
    row = connection.execute(
        'SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s',
        (schema, table),
    ).fetchone()
    return row is not None


def _query_value(connection: psycopg.Connection, sql: str, params: tuple[object, ...] = ()):
    row = connection.execute(sql, params).fetchone()
    return row[0] if row is not None else None


def _active_preview_request(container: PostgresContainer) -> tuple[str, int] | None:
    with container.connect() as connection:
        row = connection.execute(
            'SELECT id, status FROM "default".compute_requests WHERE kind = %s ORDER BY created_at DESC LIMIT 1',
            (enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,),
        ).fetchone()
    if row is None or row[1] not in {
        enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
    }:
        return None
    return str(row[0]), int(row[1])


SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n'
INTERNAL_API_TOKEN = 'dataforge-runtime-test-internal-token'
ENGINE_TEST_IMAGE = 'data-forge-polars-engine:integration'


def _http_base_url(port: int) -> str:
    return f'http://{LOCAL_SERVICE_HOST}:{port}'


def _websocket_url(port: int, path: str) -> str:
    return f'ws://{LOCAL_SERVICE_HOST}:{port}{path}'


def _make_csv(rows: int) -> str:
    header = 'id,name,age,city,score\n'
    body = ''.join(f'{index},name-{index},{20 + (index % 50)},city-{index % 100},{index % 1000}\n' for index in range(1, rows + 1))
    return header + body


def _runtime_env(
    *,
    data_dir: Path,
    database_url: str,
    port: int,
    grpc_port: int,
    rustfs: RustfsContainer,
    data_plane_port: int | None = None,
) -> dict[str, str]:
    target_port = grpc_port
    worker_data_plane_port = data_plane_port if data_plane_port is not None else 50052
    return docker_env(
        {
            'ENV_FILE': '',
            'APP_NAME': 'Data-Forge Runtime Test',
            'APP_VERSION': '0.0.0-test',
            'DEBUG': 'false',
            'PROD_MODE_ENABLED': 'false',
            'PORT': str(port),
            'HOST': local_service_bind_address(),
            'DATA_DIR': str(data_dir),
            'DATABASE_URL': database_url,
            'DISTRIBUTED_RUNTIME_ENABLED': 'true',
            'DEFAULT_NAMESPACE': 'default',
            'AUTH_REQUIRED': 'false',
            'LOG_LEVEL': 'warning',
            'UVICORN_ACCESS_LOG': 'false',
            'WORKERS': '1',
            'WORKER_CONNECTIONS': '100',
            'CORS_ORIGINS': _http_base_url(port),
            'AUTH_FRONTEND_URL': _http_base_url(port),
            'OBJECT_STORE_ENDPOINT': rustfs.endpoint,
            'OBJECT_STORE_REGION': 'us-east-1',
            'OBJECT_STORE_ACCESS_KEY': rustfs.access_key,
            'OBJECT_STORE_SECRET_KEY': rustfs.secret_key,
            'INTERNAL_API_TOKEN': INTERNAL_API_TOKEN,
            'INTERNAL_GRPC_HOST': local_service_bind_address(),
            'INTERNAL_GRPC_PORT': str(grpc_port),
            'INTERNAL_GRPC_TARGET': f'{LOCAL_SERVICE_HOST}:{target_port}',
            'RUNTIME_COORDINATOR_TARGET': f'{LOCAL_SERVICE_HOST}:{target_port}',
            'WORKER_DATA_PLANE_GRPC_HOST': local_service_bind_address(),
            'WORKER_DATA_PLANE_GRPC_PORT': str(worker_data_plane_port),
            'WORKER_DATA_PLANE_GRPC_TARGET': f'{LOCAL_SERVICE_HOST}:{worker_data_plane_port}',
        }
    )


@pytest.fixture(scope='module')
def engine_runtime_env(rustfs_container: RustfsContainer) -> Generator[dict[str, str]]:
    """Use the engine image built by the canonical test recipe before pytest starts."""
    require_docker()
    run_command(
        ['docker', 'image', 'inspect', ENGINE_TEST_IMAGE],
        cwd=CORE_ROOT,
        env=docker_env(),
    )
    docker_host = run_command(
        ['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'],
        cwd=CORE_ROOT.parent.parent,
        env=docker_env(),
    ).stdout.strip()
    if not docker_host:
        raise RuntimeError('Docker context did not provide a daemon endpoint')
    network_label = 'data-forge.test-engine-network=1'
    network_name = f'dataforge-integration-engine-{uuid.uuid4().hex[:10]}'
    run_command(
        ['docker', 'network', 'create', '--label', network_label, network_name],
        env=docker_env(),
        timeout=120,
    )
    try:
        run_command(['docker', 'network', 'connect', network_name, rustfs_container.name], env=docker_env(), timeout=120)
        yield {
            'ENGINE_IMAGE': ENGINE_TEST_IMAGE,
            'ENGINE_DOCKER_HOST': docker_host,
            'ENGINE_DOCKER_NETWORK': network_name,
            'ENGINE_OBJECT_STORE_ENDPOINT': f'http://{rustfs_container.name}:9000',
            'ENGINE_CONNECT_HOST': LOCAL_SERVICE_HOST,
        }
    finally:
        run_command(['docker', 'network', 'disconnect', '--force', network_name, rustfs_container.name], env=docker_env(), check=False, timeout=120)
        run_command(['docker', 'network', 'rm', network_name], env=docker_env(), check=False, timeout=120)


def _init_runtime_db(env: dict[str, str]) -> None:
    run_command(
        [
            'uv',
            'run',
            'python',
            '-c',
            'import asyncio; from backend_core.database import init_db; asyncio.run(init_db())',
        ],
        cwd=CORE_ROOT,
        env=env,
        timeout=300,
    )


def _upload_datasource(client, name: str, *, content: str = SAMPLE_CSV) -> str:
    response = client.post(
        '/api/v1/datasource/upload',
        files={'file': (f'{name}.csv', content.encode('utf-8'), 'text/csv')},
        data={'name': name},
    )
    assert response.status_code == 200, response.text
    return str(response.json()['id'])


def _registered_worker_count(container: PostgresContainer, kind: str) -> int:
    with container.connect() as connection:
        value = _query_value(
            connection,
            'SELECT count(*) FROM public.runtime_workers WHERE kind = %s AND stopped_at IS NULL',
            (kind,),
        )
    return int(value) if value is not None else 0


def _worker_registration_count(container: PostgresContainer, kind: str) -> int:
    with container.connect() as connection:
        value = _query_value(connection, 'SELECT count(*) FROM public.runtime_workers WHERE kind = %s', (kind,))
    return int(value) if value is not None else 0


def _coordinator_generation(container: PostgresContainer) -> int:
    with container.connect() as connection:
        value = _query_value(connection, 'SELECT generation FROM public.runtime_coordinator_state WHERE singleton_id = 1')
    return int(value) if value is not None else 0


def _runtime_coordinator(
    *,
    data_dir: Path,
    database_url: str,
    grpc_port: int,
    data_plane_port: int,
    rustfs: RustfsContainer,
    extra_env: dict[str, str] | None = None,
) -> ManagedProcess:
    env = _runtime_env(
        data_dir=data_dir,
        database_url=database_url,
        port=free_port(),
        grpc_port=grpc_port,
        rustfs=rustfs,
        data_plane_port=data_plane_port,
    )
    if extra_env:
        env.update(extra_env)
    return ManagedProcess(
        name='runtime-coordinator',
        command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'runtime_coordinator.py')],
        cwd=CORE_ROOT,
        env=env,
    )


def _worker_manager(
    *,
    data_dir: Path,
    database_url: str,
    grpc_port: int,
    data_plane_port: int,
    rustfs: RustfsContainer,
    extra_env: dict[str, str] | None = None,
) -> ManagedProcess:
    env = _runtime_env(
        data_dir=data_dir,
        database_url=database_url,
        port=free_port(),
        grpc_port=grpc_port,
        rustfs=rustfs,
        data_plane_port=data_plane_port,
    )
    if extra_env:
        env.update(extra_env)
    return ManagedProcess(
        name='worker-manager',
        command=['uv', 'run', '--no-env-file', str(WORKER_ROOT / 'main.py')],
        cwd=WORKER_ROOT,
        env=env,
    )


def _create_analysis(
    client,
    name: str,
    datasource_id: str,
    *,
    steps: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    result_id = str(uuid.uuid4())
    tab_id = str(uuid.uuid4())
    tab_steps = steps or [
        {
            'id': str(uuid.uuid4()),
            'type': 'view',
            'config': {},
            'depends_on': [],
            'is_applied': True,
        }
    ]
    response = client.post(
        '/api/v1/analysis',
        json={
            'name': name,
            'description': None,
            'tabs': [
                {
                    'id': tab_id,
                    'name': 'Source 1',
                    'parent_id': None,
                    'datasource': {
                        'id': datasource_id,
                        'analysis_tab_id': None,
                        'config': {'branch': 'master'},
                    },
                    'output': {
                        'result_id': result_id,
                        'datasource_type': 'iceberg',
                        'format': 'parquet',
                        'filename': 'source_1',
                        'build_mode': 'full',
                        'iceberg': {
                            'namespace': 'outputs',
                            'table_name': 'source_1',
                            'branch': 'master',
                        },
                    },
                    'steps': tab_steps,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _start_build(client, analysis: dict[str, object]) -> str:
    pipeline = analysis['pipeline_definition']
    assert isinstance(pipeline, dict)
    analysis_id = analysis['id']
    assert isinstance(analysis_id, str)
    tabs = pipeline.get('tabs')
    assert isinstance(tabs, list) and tabs
    first_tab = tabs[0]
    assert isinstance(first_tab, dict)
    tab_id = first_tab.get('id')
    assert isinstance(tab_id, str)
    response = client.post(
        '/api/v1/compute/builds',
        json={
            'analysis_pipeline': {
                'analysis_id': analysis_id,
                **pipeline,
            },
            'tab_id': tab_id,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()['build_id'])


def _wait_for_running_build(client, build_id: str, *, timeout: float = 180) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f'/api/v1/compute/builds/{build_id}')
        if response.status_code == 200:
            detail = dict(response.json())
            if detail.get('status') == 'running':
                return detail
            if detail.get('status') in {'completed', 'failed', 'cancelled'}:
                raise AssertionError(f'Build {build_id} reached terminal state before cancellation: {detail}')
        time.sleep(0.5)
    raise AssertionError(f'Timed out waiting for build {build_id} to start running')


def _slow_steps() -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    prev: str | None = None
    for index in range(40):
        step_id = str(uuid.uuid4())
        step = {
            'id': step_id,
            'type': 'filter',
            'config': {
                'conditions': [
                    {
                        'column': 'score',
                        'operator': '>',
                        'value': index,
                        'value_type': 'number',
                    }
                ],
                'logic': 'AND',
            },
            'depends_on': [prev] if prev is not None else [],
            'is_applied': True,
        }
        steps.append(step)
        prev = step_id
    return steps


@pytest.mark.timeout(300)
def test_init_db_bootstraps_public_and_tenant_schemas_in_postgres(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from alembic import command

    from backend_core import compute_requests_service, database
    from backend_core.config import settings
    from backend_core.migrations import _alembic_config, migrate_runtime
    from backend_core.namespace import namespace_paths, reset_namespace, set_namespace_context

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        namespace_paths('default')
        namespace_paths('alpha')

        asyncio.run(database.init_db())

        with container.connect() as connection:
            assert _table_exists(connection, 'public', 'app_settings')
            assert not _table_exists(connection, 'public', 'users')
            assert _table_exists(connection, 'public', 'runtime_workers')
            assert _table_exists(connection, 'public', 'engine_instances')
            assert _table_exists(connection, 'public', 'runtime_namespace_work')
            assert _table_exists(connection, 'public', 'runtime_namespace_work_wakes')
            assert _table_exists(connection, 'public', 'runtime_coordinator_state')
            assert _query_value(connection, 'SELECT generation FROM public.runtime_coordinator_state WHERE singleton_id = 1') == 0
            assert _table_exists(connection, 'default', 'build_runs')
            assert _table_exists(connection, 'default', 'build_jobs')
            assert _table_exists(connection, 'default', 'runtime_outbox_events')
            assert _table_exists(connection, 'default', 'notification_delivery_receipts')
            assert _table_exists(connection, 'alpha', 'build_runs')
            assert _table_exists(connection, 'alpha', 'build_jobs')
            assert _table_exists(connection, 'alpha', 'runtime_outbox_events')
            assert _table_exists(connection, 'alpha', 'notification_delivery_receipts')
            assert _query_value(connection, 'SELECT count(*) FROM public.app_settings') == 1
            assert _query_value(connection, 'SELECT version_num FROM public.alembic_version') == _PUBLIC_REVISION
            assert _query_value(connection, 'SELECT version_num FROM "default".alembic_version') == _TENANT_REVISION
            assert _query_value(connection, 'SELECT version_num FROM alpha.alembic_version') == _TENANT_REVISION
            assert _table_exists(connection, 'default', 'compute_request_flights')

        command_message = compute_pb2.ComputeCommand()
        command_message.preview.analysis_id = 'analysis-migration-test'
        command_message.preview.target_step_id = 'source'
        command_message.preview.row_limit = 100
        command_message.preview.page = 1
        command_message.preview.analysis_pipeline.analysis_id = 'analysis-migration-test'
        namespace_token = set_namespace_context('default')
        try:
            with Session(database._get_tenant_engine()) as session:
                request, created = compute_requests_service.stage_shared_flight_request(
                    session,
                    namespace='default',
                    kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                    command=command_message,
                )
                assert created is True
                request_id = request.id
                session.commit()
        finally:
            reset_namespace(namespace_token)

        migration_config = _alembic_config(scope='tenant', schema='default')
        command.downgrade(migration_config, '0011_namespace_preview_flights', tag='tenant')
        with container.connect() as connection:
            old_key = _query_value(
                connection,
                'SELECT preview_key FROM "default".compute_request_preview_flights WHERE request_id = %s',
                (request_id,),
            )
            assert isinstance(old_key, str)

        migrate_runtime(['default'])
        with container.connect() as connection:
            new_key = _query_value(
                connection,
                'SELECT flight_key FROM "default".compute_request_flights WHERE request_id = %s',
                (request_id,),
            )
            assert new_key == old_key

        _clear_database_state()


@pytest.mark.timeout(120)
def test_runtime_database_transactions_reject_a_stale_coordinator_generation(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from sqlalchemy import text
    from sqlmodel import Session

    from backend_core import database
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        with container.connect() as connection:
            connection.execute('UPDATE public.runtime_coordinator_state SET generation = 1 WHERE singleton_id = 1')
            connection.commit()

        database.set_active_runtime_coordinator_generation(1)
        try:
            with Session(database.get_settings_engine()) as session:
                assert session.execute(text('SELECT 1')).scalar_one() == 1

            with container.connect() as connection:
                connection.execute('UPDATE public.runtime_coordinator_state SET generation = 2 WHERE singleton_id = 1')
                connection.commit()

            with (
                Session(database.get_settings_engine()) as session,
                pytest.raises(database.RuntimeCoordinatorFenced, match='generation 1 is fenced by generation 2'),
            ):
                session.execute(text('SELECT 1'))
        finally:
            database.set_active_runtime_coordinator_generation(None)
            _clear_database_state()


@pytest.mark.timeout(300)
def test_runtime_work_migration_backfills_existing_tenant_work(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database, runtime_outbox_service
    from backend_core.config import settings
    from backend_core.migrations import migrate_runtime
    from backend_core.persistence.scheduler.models import Schedule

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        with Session(database._get_tenant_engine()) as session:
            runtime_outbox_service.enqueue_build_job_notification(session)
            schedule = Schedule(
                id='existing-schedule',
                datasource_id='source-datasource',
                cron_expression='* * * * *',
                enabled=True,
                next_run=datetime.now(UTC) + timedelta(minutes=5),
                created_at=datetime.now(UTC),
            )
            session.add(schedule)
            session.commit()

        # Simulate an upgrade from the last schema before the durable index.
        # The tenant event survives; the public recovery marker does not.
        with container.connect() as connection:
            connection.execute('DROP TABLE public.runtime_namespace_work_wakes')
            connection.execute('DROP TABLE public.runtime_namespace_work')
            connection.execute('DROP TABLE public.runtime_coordinator_state')
            connection.execute('DROP TABLE public.mcp_pending_actions')
            connection.execute('UPDATE public.alembic_version SET version_num = %s', ('0001_runtime_public',))
            connection.commit()

        migrate_runtime(['default'])

        with container.connect() as connection:
            assert (
                _query_value(
                    connection,
                    'SELECT pending FROM public.runtime_namespace_work WHERE namespace = %s AND kind = %s',
                    ('default', 'schedule'),
                )
                is True
            )
            schedule_work = connection.execute(
                'SELECT pending, generation, processed_generation, due_at FROM public.runtime_namespace_work WHERE namespace = %s AND kind = %s',
                ('default', 'schedule'),
            ).fetchone()
            assert schedule_work is not None
            assert schedule_work[0] is True
            assert schedule_work[1] == 1
            assert schedule_work[2] == 0
            assert schedule_work[3] is not None
            assert _query_value(connection, 'SELECT version_num FROM public.alembic_version') == _PUBLIC_REVISION

        _clear_database_state()


@pytest.mark.timeout(300)
def test_schedule_work_generation_preserves_wakeup_during_scan(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database, runtime_work_service
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        due_at = datetime.now(UTC) + timedelta(hours=1)
        with Session(database._get_tenant_engine()) as session:
            runtime_work_service.mark_schedule_pending(session, namespace='default')
            session.commit()
            assert runtime_work_service.list_due_schedule_namespaces(session) == [('default', 1)]

            runtime_work_service.mark_schedule_pending(session, namespace='default')
            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=1,
                due_at=due_at,
            )
            session.commit()
            assert runtime_work_service.list_due_schedule_namespaces(session) == [('default', 2)]

            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=2,
                due_at=due_at,
            )
            session.commit()
            assert runtime_work_service.list_due_schedule_namespaces(session) == []

            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=2,
                due_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            session.commit()
            assert runtime_work_service.list_due_schedule_namespaces(session) == [('default', 2)]

        _clear_database_state()


@pytest.mark.timeout(300)
def test_runtime_work_recovers_expired_leases_and_preserves_concurrent_enqueue(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import build_jobs_service, compute_requests_service, database, runtime_work_service
    from backend_core.config import settings
    from backend_core.persistence.build_jobs.models import BuildJob
    from backend_core.persistence.compute_requests.models import ComputeRequest

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        now = datetime.now(UTC)
        request = ComputeRequest(
            id='recover-compute',
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
            command_envelope=b'{}',
            attempts=0,
            max_attempts=1,
            created_at=now,
            updated_at=now,
        )
        with Session(database._get_tenant_engine()) as session:
            session.add(request)
            runtime_work_service.append_wake(session, namespace='default', kind=runtime_work_service.RuntimeWorkKind.COMPUTE)
            session.commit()

            claimed_request = compute_requests_service.claim_next_request(session, worker_id='runtime')
            assert claimed_request is not None
            assert runtime_work_service.list_pending_namespaces(session) == ['default']

            # Empty claims stay cheap. The namespace recovery pass below owns
            # queue-state refresh, rather than making every idle claim lane
            # scan the queue and contend on its marker.
            assert compute_requests_service.claim_next_request(session, worker_id='runtime') is None
            assert runtime_work_service.list_pending_namespaces(session) == ['default']

            assert compute_requests_service.reconcile_expired_requests(session) == 0
            marker = session.execute(text("SELECT pending, due_at FROM public.runtime_namespace_work WHERE namespace = 'default' AND kind = 'compute'")).one()
            assert marker.pending is False
            assert marker.due_at is not None and marker.due_at > datetime.now(UTC)
            assert runtime_work_service.list_pending_namespaces(session) == []

            expired_at = datetime.now(UTC) - timedelta(seconds=1)
            session.execute(
                text('UPDATE compute_requests SET lease_expires_at = :expired_at WHERE id = :request_id'),
                {'expired_at': expired_at, 'request_id': request.id},
            )
            session.execute(
                text("UPDATE public.runtime_namespace_work SET due_at = :expired_at WHERE namespace = 'default' AND kind = 'compute'"),
                {'expired_at': expired_at},
            )
            session.commit()
            assert runtime_work_service.list_pending_namespaces(session) == ['default']

            assert compute_requests_service.reconcile_expired_requests(session) == 1
            assert compute_requests_service.claim_next_request(session, worker_id='runtime') is None
            assert runtime_work_service.list_pending_namespaces(session) == []

            build = build_jobs_service.stage_job(
                session,
                build_id='recover-build',
                namespace='default',
                max_attempts=1,
            )
            build_job_id = build.id
            session.commit()
            claimed_build = build_jobs_service.claim_next_job(session, worker_id='runtime')
            assert claimed_build is not None
            assert build_jobs_service.stage_exhausted_jobs(session) == []
            marker = session.execute(text("SELECT pending, due_at FROM public.runtime_namespace_work WHERE namespace = 'default' AND kind = 'build'")).one()
            assert marker.pending is False
            assert marker.due_at is not None and marker.due_at > datetime.now(UTC)
            assert runtime_work_service.list_pending_namespaces(session) == []

            expired_at = datetime.now(UTC) - timedelta(seconds=1)
            session.execute(
                text('UPDATE build_jobs SET lease_expires_at = :expired_at WHERE id = :job_id'),
                {'expired_at': expired_at, 'job_id': build_job_id},
            )
            session.execute(
                text("UPDATE public.runtime_namespace_work SET due_at = :expired_at WHERE namespace = 'default' AND kind = 'build'"),
                {'expired_at': expired_at},
            )
            session.commit()
            assert runtime_work_service.list_pending_namespaces(session) == ['default']

            assert build_jobs_service.expire_exhausted_jobs(session) == [build.build_id]
            assert build_jobs_service.claim_next_job(session, worker_id='runtime') is None
            assert runtime_work_service.list_pending_namespaces(session) == []

        producer = Session(database._get_tenant_engine())
        racing_request_id = 'racing-compute'
        racing_request = ComputeRequest(
            id=racing_request_id,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
            command_envelope=b'{}',
            attempts=0,
            max_attempts=1,
            created_at=now,
            updated_at=now,
        )
        producer.add(racing_request)
        producer.flush()
        runtime_work_service.append_wake(producer, namespace='default', kind=runtime_work_service.RuntimeWorkKind.COMPUTE)

        consumer_started = threading.Event()
        consumer_result: list[ComputeRequest | None] = []
        consumer_errors: list[BaseException] = []

        def consume_while_enqueue_is_uncommitted() -> None:
            try:
                with Session(database._get_tenant_engine()) as consumer:
                    consumer_started.set()
                    consumer_result.append(compute_requests_service.claim_next_request(consumer, worker_id='runtime'))
            except BaseException as exc:
                consumer_errors.append(exc)

        consumer_thread = threading.Thread(target=consume_while_enqueue_is_uncommitted)
        consumer_thread.start()
        assert consumer_started.wait(timeout=5)
        consumer_thread.join(timeout=10)
        assert not consumer_thread.is_alive(), 'empty claim blocked behind an uncommitted enqueue marker'
        assert not consumer_errors
        assert consumer_result == [None]

        producer.commit()
        producer.close()

        with Session(database._get_tenant_engine()) as session:
            assert runtime_work_service.list_pending_namespaces(session) == ['default']
            assert session.get(ComputeRequest, racing_request_id) is not None
            assert session.get(BuildJob, build_job_id) is not None

            request_to_delete = session.get(ComputeRequest, racing_request_id)
            assert request_to_delete is not None
            session.delete(request_to_delete)
            session.commit()
            session.execute(text("UPDATE public.runtime_namespace_work SET pending = FALSE, due_at = NULL WHERE namespace = 'default' AND kind = 'compute'"))
            session.commit()

        refresh_pid: list[int] = []
        refresh_errors: list[BaseException] = []
        refresh_finished = threading.Event()

        def refresh_during_enqueue() -> None:
            try:
                with Session(database._get_tenant_engine()) as refresh_session:
                    refresh_pid.append(int(refresh_session.execute(text('SELECT pg_backend_pid()')).scalar_one()))
                    runtime_work_service.refresh_pending_work(
                        refresh_session,
                        namespace='default',
                        kind=runtime_work_service.RuntimeWorkKind.COMPUTE,
                        pending_query="""
                            WITH delay AS MATERIALIZED (SELECT pg_sleep(4))
                            SELECT 1 FROM delay WHERE random() < 0
                        """,
                    )
                    refresh_session.commit()
            except BaseException as exc:
                refresh_errors.append(exc)
            finally:
                refresh_finished.set()

        refresh_thread = threading.Thread(target=refresh_during_enqueue)
        refresh_thread.start()
        scanning = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with container.connect() as connection:
                state = (
                    connection.execute(
                        "SELECT wait_event FROM pg_stat_activity WHERE pid = %s AND position('pg_sleep(4)' in query) > 0",
                        (refresh_pid[0],),
                    ).fetchone()
                    if refresh_pid
                    else None
                )
            if state is not None and state[0] == 'PgSleep':
                scanning = True
                break
            time.sleep(0.01)
        assert scanning, 'queue-state scan did not enter its deliberately slow phase'

        producer_finished = threading.Event()
        producer_errors: list[BaseException] = []

        def enqueue_during_scan() -> None:
            try:
                with Session(database._get_tenant_engine()) as producer_session:
                    producer_session.add(
                        ComputeRequest(
                            id='enqueue-during-refresh',
                            namespace='default',
                            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                            status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
                            command_envelope=b'{}',
                            attempts=0,
                            max_attempts=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    producer_session.flush()
                    runtime_work_service.append_wake(
                        producer_session,
                        namespace='default',
                        kind=runtime_work_service.RuntimeWorkKind.COMPUTE,
                    )
                    producer_session.commit()
            except BaseException as exc:
                producer_errors.append(exc)
            finally:
                producer_finished.set()

        producer_thread = threading.Thread(target=enqueue_during_scan)
        producer_thread.start()
        assert producer_finished.wait(timeout=2), 'producer blocked behind the queue-state scan'
        producer_thread.join(timeout=1)
        assert not producer_errors
        assert not refresh_finished.is_set(), 'the queue-state scan finished before the enqueue was checked'

        refresh_thread.join(timeout=10)
        assert not refresh_thread.is_alive()
        assert not refresh_errors
        with Session(database._get_tenant_engine()) as session:
            marker = session.execute(text("SELECT pending FROM public.runtime_namespace_work WHERE namespace = 'default' AND kind = 'compute'")).one()
            assert marker.pending is False, 'the older queue snapshot incorrectly changed the durable queue state'
            assert (
                session.execute(text("SELECT 1 FROM public.runtime_namespace_work_wakes WHERE namespace = 'default' AND kind = 'compute' LIMIT 1")).first()
                is not None
            ), 'a wake committed after capture was deleted by the older queue scan'
            assert runtime_work_service.list_pending_namespaces(session) == ['default']
            assert session.get(ComputeRequest, 'enqueue-during-refresh') is not None

        _clear_database_state()


@pytest.mark.timeout(300)
def test_postgres_compute_claims_are_serialized_per_engine_identity(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import compute_requests_service, database
    from backend_core.config import settings
    from backend_core.namespace import reset_namespace, set_namespace_context
    from backend_core.persistence.compute_requests.models import ComputeRequest

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        now = datetime.now(UTC)
        requests = [
            ComputeRequest(
                id=request_id,
                namespace='default',
                kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
                engine_scope=enums_pb2.ENGINE_SCOPE_ANALYSIS_INTERACTIVE,
                engine_reuse_policy=enums_pb2.ENGINE_REUSE_POLICY_SHARED,
                engine_resource_id='analysis-shared-identity',
                command_envelope=b'{}',
                attempts=0,
                max_attempts=3,
                created_at=now,
                updated_at=now,
            )
            for request_id in ('claim-first-command', 'claim-second-command')
        ]
        request_ids = [request.id for request in requests]
        namespace_token = set_namespace_context('default')
        try:
            with Session(database._get_tenant_engine()) as session:
                session.add_all(requests)
                session.commit()

            original_lock = compute_requests_service._lock_engine_claim
            both_candidates_selected = threading.Barrier(2)
            selected_ids: list[str] = []
            selected_ids_lock = threading.Lock()

            def synchronize_claims(session: Session, request: ComputeRequest) -> bool:
                with selected_ids_lock:
                    selected_ids.append(request.id)
                both_candidates_selected.wait(timeout=10)
                return original_lock(session, request)

            monkeypatch.setattr(compute_requests_service, '_lock_engine_claim', synchronize_claims)
            claims: list[ComputeRequest | None] = []
            errors: list[BaseException] = []

            def claim(worker_id: str) -> None:
                token = set_namespace_context('default')
                try:
                    with Session(database._get_tenant_engine()) as session:
                        claims.append(compute_requests_service.claim_next_request(session, worker_id=worker_id))
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    reset_namespace(token)

            threads = [threading.Thread(target=claim, args=(f'worker-{index}',)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

            assert all(not thread.is_alive() for thread in threads)
            assert not errors
            assert set(selected_ids) == {'claim-first-command', 'claim-second-command'}
            assert sum(claim is not None for claim in claims) == 1

            with Session(database._get_tenant_engine()) as session:
                stored_requests = [session.get(ComputeRequest, request_id) for request_id in request_ids]
            assert all(request is not None for request in stored_requests)
            statuses = [request.status for request in stored_requests if request is not None]
            assert statuses.count(enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING) == 1
            assert statuses.count(enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED) == 1
        finally:
            reset_namespace(namespace_token)
            _clear_database_state()


@pytest.mark.timeout(300)
def test_postgres_outbox_dispatchers_do_not_share_unclaimed_batch_rows(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database, runtime_outbox_service
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        with Session(database._get_tenant_engine()) as session:
            first = runtime_outbox_service.enqueue_build_job_notification(session)
            second = runtime_outbox_service.enqueue_build_job_notification(session)
            session.commit()
            event_ids = [first.id, second.id]

        with container.connect() as connection:
            assert (
                _query_value(
                    connection,
                    'SELECT count(*) FROM public.runtime_namespace_work_wakes WHERE namespace = %s AND kind = %s',
                    ('default', 'outbox'),
                )
                >= 1
            )

        delivered: list[str] = []
        delivery_lock = threading.Lock()
        second_delivery_started = threading.Event()
        release_second_delivery = threading.Event()

        def deliver(_session: Session, payload: dict[str, object]) -> None:
            event_id = str(payload['event_id'])
            with delivery_lock:
                delivered.append(event_id)
                delivery_number = len(delivered)
            if delivery_number == 2 and threading.current_thread().name == 'dispatcher-a':
                second_delivery_started.set()
                assert release_second_delivery.wait(timeout=30)

        monkeypatch.setattr(runtime_outbox_service.runtime_ipc, 'notify_runtime_payload_on_commit', deliver)

        def dispatch() -> None:
            with Session(database._get_tenant_engine()) as session:
                runtime_outbox_service.dispatch_pending_events(session, limit=2)

        dispatcher_a = threading.Thread(target=dispatch, name='dispatcher-a')
        dispatcher_a.start()
        assert second_delivery_started.wait(timeout=30)

        dispatcher_b = threading.Thread(target=dispatch, name='dispatcher-b')
        dispatcher_b.start()
        dispatcher_b.join(timeout=30)
        assert not dispatcher_b.is_alive()
        release_second_delivery.set()
        dispatcher_a.join(timeout=30)
        assert not dispatcher_a.is_alive()

        assert sorted(delivered) == sorted(event_ids)
        with container.connect() as connection:
            assert (
                _query_value(
                    connection,
                    'SELECT count(*) FROM public.runtime_namespace_work_wakes WHERE namespace = %s AND kind = %s',
                    ('default', 'outbox'),
                )
                == 0
            )
        _clear_database_state()


@pytest.mark.timeout(300)
def test_postgres_outbox_runtime_dispatch_batches_claim_and_finalize_transactions(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from sqlalchemy import event as sa_event

    from backend_core import database, runtime_outbox_service
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())
        engine = database._get_tenant_engine()

        with Session(engine) as session:
            events = [runtime_outbox_service.enqueue_build_job_notification(session) for _ in range(3)]
            session.commit()
            event_ids = [event.id for event in events]

        notification_payloads: list[dict[str, object]] = []
        commits: list[None] = []

        def notify_in_transaction(session: Session, payload: dict[str, object]) -> None:
            assert session.in_transaction()
            notification_payloads.append(payload)

        def capture_commit(_connection) -> None:
            commits.append(None)

        sa_event.listen(engine, 'commit', capture_commit)
        monkeypatch.setattr(runtime_outbox_service.runtime_ipc, 'notify_runtime_payload_on_commit', notify_in_transaction)
        try:
            with Session(engine) as session:
                assert runtime_outbox_service.dispatch_pending_events(session, limit=3) == 3
        finally:
            sa_event.remove(engine, 'commit', capture_commit)

        with Session(engine) as session:
            stored = [session.get(runtime_outbox_service.RuntimeOutboxEvent, event_id) for event_id in event_ids]
        assert all(event is not None and event.status == runtime_outbox_service.RuntimeOutboxStatus.DISPATCHED for event in stored)
        assert {str(payload['event_id']) for payload in notification_payloads} == set(event_ids)
        assert len(commits) == 3
        _clear_database_state()


@pytest.mark.timeout(300)
def test_postgres_outbox_claim_recovers_after_dispatcher_process_crash(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database, runtime_outbox_service
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        with Session(database._get_tenant_engine()) as session:
            event = runtime_outbox_service.enqueue_build_job_notification(session)
            session.commit()
            event_id = event.id

        env = docker_env({'ENV_FILE': '', 'DATABASE_URL': container.url, 'DEFAULT_NAMESPACE': 'default', 'DISTRIBUTED_RUNTIME_ENABLED': 'true'})
        claimant = ManagedProcess(
            name='outbox-claimant',
            command=[
                'uv',
                'run',
                'python',
                '-c',
                (
                    'import time; from sqlmodel import Session; from backend_core import database, runtime_outbox_service; '
                    'session = Session(database._get_tenant_engine()); '
                    'assert runtime_outbox_service._claim_next_event(session) is not None; time.sleep(300)'
                ),
            ],
            cwd=CORE_ROOT,
            env=env,
        )
        try:
            claimant.start()
            wait_for_condition(
                lambda: _outbox_status(container, event_id) == 'dispatching',
                timeout=30,
                description='outbox event to be claimed by crash target',
            )
        finally:
            claimant.crash()

        with container.connect() as connection:
            connection.execute(
                'UPDATE "default".runtime_outbox_events SET lease_expires_at = CURRENT_TIMESTAMP - INTERVAL \'1 second\' WHERE id = %s',
                (event_id,),
            )
            connection.commit()

        run_command(
            [
                'uv',
                'run',
                'python',
                '-c',
                (
                    'from sqlmodel import Session; from backend_core import database, runtime_outbox_service; '
                    'session = Session(database._get_tenant_engine()); '
                    'assert runtime_outbox_service.dispatch_pending_events(session, limit=1) == 1'
                ),
            ],
            cwd=CORE_ROOT,
            env=env,
            timeout=60,
        )

        with container.connect() as connection:
            row = connection.execute(
                'SELECT status, attempts FROM "default".runtime_outbox_events WHERE id = %s',
                (event_id,),
            ).fetchone()
        assert row == ('dispatched', 2)
        _clear_database_state()


def _outbox_status(container: PostgresContainer, event_id: str) -> str | None:
    with container.connect() as connection:
        value = _query_value(
            connection,
            'SELECT status FROM "default".runtime_outbox_events WHERE id = %s',
            (event_id,),
        )
    return str(value) if value is not None else None


@pytest.mark.timeout(300)
def test_init_db_postgres_shared_seed_is_safe_under_concurrent_startup(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        errors: list[BaseException] = []

        def run_init() -> None:
            try:
                asyncio.run(database.init_db())
            except BaseException as exc:  # pragma: no cover - exercised only on failure
                errors.append(exc)

        first = threading.Thread(target=run_init)
        second = threading.Thread(target=run_init)
        first.start()
        second.start()
        first.join(timeout=60)
        second.join(timeout=60)

        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []

        with container.connect() as connection:
            assert _query_value(connection, 'SELECT count(*) FROM public.app_settings') == 1
            assert not _table_exists(connection, 'public', 'users')

        _clear_database_state()


@pytest.mark.timeout(300)
def test_backend_public_bootstrap_creates_auth_tables_and_default_user(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database
    from backend_core.auth_config import settings as auth_settings
    from backend_core.config import settings
    from backend_core.public_schema import ensure_backend_public_tables
    from modules.auth.service import ensure_default_user

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        monkeypatch.setattr(auth_settings, 'default_user_email', 'seeded@example.com', raising=False)
        monkeypatch.setattr(auth_settings, 'default_user_password', 'SeededPass123', raising=False)
        monkeypatch.setattr(auth_settings, 'default_user_name', 'Seeded User', raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())
        ensure_backend_public_tables()
        database.run_settings_db(ensure_default_user)

        with container.connect() as connection:
            assert _table_exists(connection, 'public', 'users')
            assert _table_exists(connection, 'public', 'auth_providers')
            assert _table_exists(connection, 'public', 'user_sessions')
            assert _table_exists(connection, 'public', 'verification_tokens')
            assert _table_exists(connection, 'public', 'chat_sessions')
            assert _query_value(connection, 'SELECT count(*) FROM public.users') == 1

        _clear_database_state()


@pytest.mark.timeout(300)
def test_init_db_postgres_namespace_bootstrap_does_not_deadlock(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database
    from backend_core.config import settings
    from backend_core.namespace import namespace_paths

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        namespace_paths('default')

        thread = threading.Thread(target=lambda: asyncio.run(database.init_db()))
        thread.start()
        thread.join(timeout=30)

        assert not thread.is_alive()

        with container.connect() as connection:
            assert _table_exists(connection, 'default', 'build_runs')

        _clear_database_state()


@pytest.mark.timeout(300)
def test_namespace_connection_sets_search_path(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database
    from backend_core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())

        with database.namespace_connection('default') as connection:
            assert connection.execute(text('SELECT current_schema()')).scalar_one() == 'default'

        _clear_database_state()


@pytest.mark.timeout(300)
def test_namespace_connection_maps_public_namespace_away_from_public_schema(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database
    from backend_core.config import settings
    from backend_core.namespace import namespace_database_schema

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())
        database.initialize_namespace_db('public')

        with database.namespace_connection('public') as connection:
            assert connection.execute(text('SELECT current_schema()')).scalar_one() == namespace_database_schema('public')

        _clear_database_state()


@pytest.mark.timeout(300)
def test_tenant_engine_checkout_tracks_current_namespace(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database
    from backend_core.config import settings
    from backend_core.namespace import reset_namespace, set_namespace_context

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())
        database.initialize_namespace_db('alpha')
        database.initialize_namespace_db('beta')

        alpha_token = set_namespace_context('alpha')
        try:
            with Session(database._get_tenant_engine()) as alpha_session:
                assert alpha_session.connection().execute(text('SELECT current_schema()')).scalar_one() == 'alpha'
        finally:
            reset_namespace(alpha_token)

        beta_token = set_namespace_context('beta')
        try:
            with Session(database._get_tenant_engine()) as beta_session:
                assert beta_session.connection().execute(text('SELECT current_schema()')).scalar_one() == 'beta'
        finally:
            reset_namespace(beta_token)

        _clear_database_state()


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_postgres_runtime_ipc_delivers_notifications(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from sqlalchemy import create_engine

    from backend_core import runtime_ipc
    from backend_core.config import settings
    from backend_core.domain.runtime.events import RuntimePayloadKind

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', tmp_path / 'data', raising=False)

        received: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        stop_event = asyncio.Event()

        async def handler(payload: dict[str, object]) -> None:
            await received.put(payload)

        server = await runtime_ipc.start_api_server()
        assert server is not None
        engine = create_engine(container.url)
        try:
            task = asyncio.create_task(runtime_ipc.serve_api_notifications(server, stop_event, handler))
            await asyncio.to_thread(runtime_ipc.notify_api_build, 'default', 'build-1', 7)
            await asyncio.to_thread(runtime_ipc.notify_build_job)

            build_payload = await asyncio.wait_for(received.get(), timeout=15)
            job_payload = await asyncio.wait_for(received.get(), timeout=15)

            assert build_payload == {
                'kind': RuntimePayloadKind.BUILD.value,
                'namespace': 'default',
                'build_id': 'build-1',
                'latest_sequence': 7,
            }
            assert job_payload == {'kind': RuntimePayloadKind.JOB.value}

            progress_payload = {
                'kind': RuntimePayloadKind.BUILD.value,
                'namespace': 'default',
                'build_id': 'build-2',
                'latest_sequence': 3,
            }
            notification_staged = threading.Event()
            commit_notification = threading.Event()

            def stage_notification() -> None:
                with Session(engine) as session, session.begin():
                    runtime_ipc.notify_runtime_payload_on_commit(session, progress_payload)
                    notification_staged.set()
                    if not commit_notification.wait(timeout=10):
                        raise TimeoutError('Test did not release the notification transaction')

            staged_task = asyncio.create_task(asyncio.to_thread(stage_notification))
            try:
                assert await asyncio.to_thread(notification_staged.wait, 5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(received.get(), timeout=0.1)
            finally:
                commit_notification.set()
                await asyncio.gather(staged_task, return_exceptions=True)
            assert await asyncio.wait_for(received.get(), timeout=15) == progress_payload
        finally:
            engine.dispose()
            stop_event.set()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout=5)
            await runtime_ipc.stop_api_server(server)


@pytest.mark.timeout(300)
def test_postgres_runtime_roles_restart_after_forced_process_exit(
    tmp_path: Path,
    rustfs_container: RustfsContainer,
    engine_runtime_env: dict[str, str],
) -> None:
    require_docker()

    with PostgresContainer() as container:
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        api_port = free_port()
        grpc_port = free_port()
        data_plane_port = free_port()
        base_env = _runtime_env(
            data_dir=data_dir,
            database_url=container.url,
            port=api_port,
            grpc_port=grpc_port,
            rustfs=rustfs_container,
            data_plane_port=data_plane_port,
        )
        base_env.update(engine_runtime_env)
        base_env['SCHEDULER_CHECK_INTERVAL'] = '1'
        _init_runtime_db(base_env)

        coordinator = _runtime_coordinator(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
        )
        worker_manager = _worker_manager(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
            extra_env=engine_runtime_env,
        )

        api = ManagedProcess(
            name='restart-api',
            command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'main.py')],
            cwd=CORE_ROOT,
            env=base_env,
        )
        scheduler = ManagedProcess(
            name='restart-scheduler',
            command=['uv', 'run', '--no-env-file', str(SCHEDULER_ROOT / 'main.py')],
            cwd=SCHEDULER_ROOT,
            env=base_env,
        )
        try:
            api.start()
            wait_for_http_ready(f'{_http_base_url(api_port)}/health/ready')
            coordinator.start()
            worker_manager.start()
            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='runtime coordinator registration before crash',
            )
            scheduler.start()
            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='runtime coordinator registration before crash',
            )
            wait_for_condition(
                lambda: _registered_worker_count(container, 'scheduler') >= 1,
                timeout=90,
                description='scheduler registration before crash',
            )

            api.restart()
            wait_for_http_ready(f'{_http_base_url(api_port)}/health/ready')

            previous_generation = _coordinator_generation(container)
            previous_worker_registrations = _worker_registration_count(container, 'coordinator')
            coordinator.restart()
            wait_for_condition(
                lambda: _coordinator_generation(container) > previous_generation,
                timeout=90,
                description='replacement runtime coordinator generation',
            )
            wait_for_condition(
                lambda: _worker_registration_count(container, 'coordinator') > previous_worker_registrations,
                timeout=90,
                description='worker manager resynchronization after coordinator restart',
            )
            previous_worker_registrations = _worker_registration_count(container, 'coordinator')
            worker_manager.restart()
            wait_for_condition(
                lambda: _worker_registration_count(container, 'coordinator') > previous_worker_registrations,
                timeout=90,
                description='replacement worker manager registration',
            )

            scheduler.restart()
            wait_for_condition(
                lambda: _registered_worker_count(container, 'scheduler') >= 2,
                timeout=90,
                description='replacement scheduler registration',
            )
        except AssertionError as exc:
            raise AssertionError(
                f'{exc}\napi tail:\n{api.tail()}\ncoordinator tail:\n{coordinator.tail()}\n'
                f'worker manager tail:\n{worker_manager.tail()}\nscheduler tail:\n{scheduler.tail()}'
            ) from exc
        finally:
            scheduler.stop()
            worker_manager.stop()
            coordinator.stop()
            api.stop()


@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_postgres_runtime_survives_api_crash_during_shared_preview_and_replays_build(
    tmp_path: Path,
    rustfs_container: RustfsContainer,
    engine_runtime_env: dict[str, str],
) -> None:
    require_docker()

    with PostgresContainer() as container:
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        api_one_port = free_port()
        api_two_port = free_port()
        coordinator_grpc_port = free_port()
        data_plane_port = free_port()

        base_env = _runtime_env(
            data_dir=data_dir,
            database_url=container.url,
            port=api_one_port,
            grpc_port=coordinator_grpc_port,
            rustfs=rustfs_container,
            data_plane_port=data_plane_port,
        )
        _init_runtime_db(base_env)

        api_one = ManagedProcess(
            name='api-one',
            command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'main.py')],
            cwd=CORE_ROOT,
            env=_runtime_env(
                data_dir=data_dir,
                database_url=container.url,
                port=api_one_port,
                grpc_port=coordinator_grpc_port,
                rustfs=rustfs_container,
                data_plane_port=data_plane_port,
            ),
        )
        api_two = ManagedProcess(
            name='api-two',
            command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'main.py')],
            cwd=CORE_ROOT,
            env=_runtime_env(
                data_dir=data_dir,
                database_url=container.url,
                port=api_two_port,
                grpc_port=coordinator_grpc_port,
                rustfs=rustfs_container,
                data_plane_port=data_plane_port,
            ),
        )
        coordinator = _runtime_coordinator(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=coordinator_grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
        )
        worker_manager = _worker_manager(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=coordinator_grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
            extra_env=engine_runtime_env,
        )
        try:
            api_one.start()
            api_two.start()
            coordinator.start()
            worker_manager.start()
            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='runtime coordinator registration',
            )
            try:
                wait_for_http_ready(f'{_http_base_url(api_one_port)}/health/ready')
                wait_for_http_ready(f'{_http_base_url(api_two_port)}/health/ready')
            except AssertionError as exc:
                raise AssertionError(
                    f'{exc}\napi-one tail:\n{api_one.tail()}\napi-two tail:\n{api_two.tail()}\ncoordinator tail:\n{coordinator.tail()}'
                ) from exc

            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='runtime coordinator to register',
            )

            import httpx

            with httpx.Client(base_url=_http_base_url(api_one_port), timeout=30) as client_one:
                datasource_id = _upload_datasource(client_one, 'cross-api-runtime', content=_make_csv(200000))
                analysis = _create_analysis(client_one, 'Cross API Runtime', datasource_id, steps=_slow_steps())
                build_id = _start_build(client_one, analysis)

                # The request is durable before the API waits for its result.
                # Kill that API process while the worker is still executing the
                # exact shared preview. A second API process must attach to the
                # same durable flight instead of starting another computation.
                pipeline = analysis['pipeline_definition']
                assert isinstance(pipeline, dict)
                analysis_id = str(analysis['id'])
                analysis_pipeline = {'analysis_id': analysis_id, **pipeline}
                tabs = pipeline.get('tabs')
                assert isinstance(tabs, list) and tabs
                first_tab = tabs[0]
                assert isinstance(first_tab, dict)
                steps = first_tab.get('steps')
                assert isinstance(steps, list) and steps
                target_step_id = str(steps[-1]['id'])
                preview_request = {
                    'analysis_id': analysis_id,
                    'target_step_id': target_step_id,
                    'analysis_pipeline': analysis_pipeline,
                    'row_limit': 50,
                    'page': 1,
                }
                preview_result: dict[str, object] = {}

                def _submit_preview_from_first_api() -> None:
                    import httpx

                    try:
                        with httpx.Client(base_url=_http_base_url(api_one_port), timeout=180) as preview_client:
                            preview_result['response'] = preview_client.post(
                                '/api/v1/compute/preview',
                                json=preview_request,
                            )
                    except BaseException as exc:
                        # The connection reset is expected after the process
                        # group is killed; the durable request is the oracle.
                        preview_result['error'] = exc

                preview_thread = threading.Thread(target=_submit_preview_from_first_api, name='api-crash-preview')
                preview_thread.start()
                try:
                    wait_for_condition(
                        lambda: _active_preview_request(container),
                        timeout=90,
                        interval=0.25,
                        description='shared preview request to become durable and active',
                    )
                except AssertionError as exc:
                    preview_response = preview_result.get('response')
                    if preview_response is None:
                        preview_outcome = repr(preview_result)
                    else:
                        preview_outcome = f'status={getattr(preview_response, "status_code", "?")} body={getattr(preview_response, "text", preview_response)!r}'
                    raise AssertionError(
                        f'{exc}; preview outcome={preview_outcome}\napi-one tail:\n{api_one.tail()}\ncoordinator tail:\n{coordinator.tail()}'
                    ) from exc
                api_one.crash()
                preview_thread.join(timeout=30)
                assert not preview_thread.is_alive(), 'crashed API preview client did not observe process termination'

            with httpx.Client(base_url=_http_base_url(api_two_port), timeout=30) as client_two:
                try:
                    preview_response = client_two.post(
                        '/api/v1/compute/preview',
                        json=preview_request,
                    )
                except httpx.HTTPError as exc:
                    raise AssertionError(
                        f'preview request failed: {exc}\napi-two tail:\n{api_two.tail()}\n'
                        f'coordinator tail:\n{coordinator.tail()}\nworker-manager tail:\n{worker_manager.tail()}'
                    ) from exc
                assert preview_response.status_code == 200, (
                    f'{preview_response.text}\napi-two tail:\n{api_two.tail()}\n'
                    f'coordinator tail:\n{coordinator.tail()}\nworker-manager tail:\n{worker_manager.tail()}'
                )
                preview_payload = dict(preview_response.json())
                assert preview_payload['data']

                with container.connect() as connection:
                    preview_request_count = _query_value(
                        connection,
                        'SELECT count(*) FROM "default".compute_requests WHERE kind = %s',
                        (enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,),
                    )
                    preview_flight_count = _query_value(
                        connection,
                        'SELECT count(*) FROM "default".compute_request_flights',
                    )
                    preview_run_count = _query_value(
                        connection,
                        'SELECT count(*) FROM "default".engine_runs WHERE kind = %s',
                        ('preview',),
                    )
                assert preview_request_count == 1
                assert preview_flight_count == 1
                assert preview_run_count == 1

                try:
                    detail = wait_for_condition(
                        lambda: (
                            response.json()
                            if (response := client_two.get(f'/api/v1/compute/builds/{build_id}')).status_code == 200
                            and response.json().get('status') in {'completed', 'failed', 'cancelled'}
                            else None
                        ),
                        timeout=180,
                        interval=1,
                        description='build detail from second api worker',
                    )
                except AssertionError as exc:
                    with container.connect() as connection:
                        build_state = connection.execute(
                            'SELECT id, status, current_step, error_message FROM "default".build_runs WHERE id = %s',
                            (build_id,),
                        ).fetchone()
                        job_state = connection.execute(
                            'SELECT status, lease_owner, last_error FROM "default".build_jobs WHERE build_id = %s',
                            (build_id,),
                        ).fetchone()
                        workers = connection.execute('SELECT kind, id, stopped_at FROM public.runtime_workers ORDER BY started_at').fetchall()
                    raise AssertionError(
                        f'{exc}\nbuild state: {build_state!r}\njob state: {job_state!r}\nworkers: {workers!r}'
                        f'\napi-one tail:\n{api_one.tail()}\napi-two tail:\n{api_two.tail()}\ncoordinator tail:\n{coordinator.tail()}'
                    ) from exc

                assert detail['build_id'] == build_id
                assert detail['status'] == 'completed', json.dumps(detail, indent=2, sort_keys=True)

            async with connect(_websocket_url(api_two_port, f'/api/v1/compute/ws/builds/{build_id}?namespace=default')) as websocket:
                snapshot = json.loads(await websocket.recv())

            assert snapshot['type'] == 'snapshot'
            assert snapshot['build']['build_id'] == build_id
            assert snapshot['build']['status'] == 'completed'
            assert isinstance(snapshot['last_sequence'], int)
            assert snapshot['last_sequence'] >= 1

            if snapshot['last_sequence'] > 1:
                async with connect(_websocket_url(api_two_port, f'/api/v1/compute/ws/builds/{build_id}?namespace=default&last_sequence=1')) as websocket:
                    replay = json.loads(await websocket.recv())

                assert replay['context']['buildId'] == build_id
                assert replay['context']['sequence'] > 1
                event_cases = {'plan', 'stepStarted', 'stepCompleted', 'stepFailed', 'progress', 'resources', 'log', 'completed', 'failed', 'cancelled'}
                assert len(event_cases & set(replay)) == 1
        finally:
            worker_manager.stop()
            coordinator.stop()
            api_two.stop()
            api_one.stop()


@pytest.mark.timeout(300)
def test_postgres_runtime_supports_cross_api_cancellation(
    tmp_path: Path,
    rustfs_container: RustfsContainer,
    engine_runtime_env: dict[str, str],
) -> None:
    require_docker()

    with PostgresContainer() as container:
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        api_one_port = free_port()
        api_two_port = free_port()
        coordinator_grpc_port = free_port()
        data_plane_port = free_port()

        base_env = _runtime_env(
            data_dir=data_dir,
            database_url=container.url,
            port=api_one_port,
            grpc_port=coordinator_grpc_port,
            rustfs=rustfs_container,
            data_plane_port=data_plane_port,
        )
        _init_runtime_db(base_env)

        api_one = ManagedProcess(
            name='api-one',
            command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'main.py')],
            cwd=CORE_ROOT,
            env=_runtime_env(
                data_dir=data_dir,
                database_url=container.url,
                port=api_one_port,
                grpc_port=coordinator_grpc_port,
                rustfs=rustfs_container,
                data_plane_port=data_plane_port,
            ),
        )
        api_two = ManagedProcess(
            name='api-two',
            command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'main.py')],
            cwd=CORE_ROOT,
            env=_runtime_env(
                data_dir=data_dir,
                database_url=container.url,
                port=api_two_port,
                grpc_port=coordinator_grpc_port,
                rustfs=rustfs_container,
                data_plane_port=data_plane_port,
            ),
        )
        coordinator = _runtime_coordinator(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=coordinator_grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
        )
        worker_manager = _worker_manager(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=coordinator_grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
            extra_env=engine_runtime_env,
        )
        try:
            api_one.start()
            api_two.start()
            coordinator.start()
            worker_manager.start()
            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='runtime coordinator registration',
            )
            try:
                wait_for_http_ready(f'{_http_base_url(api_one_port)}/health/ready')
                wait_for_http_ready(f'{_http_base_url(api_two_port)}/health/ready')
            except AssertionError as exc:
                raise AssertionError(
                    f'{exc}\napi-one tail:\n{api_one.tail()}\napi-two tail:\n{api_two.tail()}\ncoordinator tail:\n{coordinator.tail()}'
                ) from exc

            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='runtime coordinator to register',
            )

            import httpx

            big_csv = _make_csv(200000)

            with httpx.Client(base_url=_http_base_url(api_one_port), timeout=30) as client_one:
                datasource_id = _upload_datasource(client_one, 'cross-api-cancel', content=big_csv)
                analysis = _create_analysis(client_one, 'Cross API Cancel', datasource_id, steps=_slow_steps())
                build_id = _start_build(client_one, analysis)
                _wait_for_running_build(client_one, build_id, timeout=180)

            with httpx.Client(base_url=_http_base_url(api_two_port), timeout=30) as client_two:
                cancelled = client_two.post(f'/api/v1/compute/builds/{build_id}/cancel')

                assert cancelled.status_code == 200, cancelled.text
                payload = dict(cancelled.json())
                assert payload['build_id'] == build_id
                assert payload['engine_run_id'] is None
                assert payload['status'] == 'cancelled'

                detail = wait_for_condition(
                    lambda: (
                        response.json()
                        if (response := client_two.get(f'/api/v1/compute/builds/{build_id}')).status_code == 200
                        and response.json().get('status') == 'cancelled'
                        else None
                    ),
                    timeout=180,
                    interval=1,
                    description='cancelled build detail from second api worker',
                )

                assert detail['build_id'] == build_id
                assert detail['current_engine_run_id'] is None
                assert detail['status'] == 'cancelled'
                assert detail['cancelled_by']

            with container.connect() as connection:
                build_status = _query_value(
                    connection,
                    'SELECT status FROM "default".build_runs WHERE id = %s',
                    (build_id,),
                )

            assert build_status == 'cancelled'
        finally:
            worker_manager.stop()
            coordinator.stop()
            api_two.stop()
            api_one.stop()
