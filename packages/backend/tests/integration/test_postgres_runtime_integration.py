from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from alembic import command
from psycopg.types.json import Json, Jsonb
from sqlalchemy import text
from sqlmodel import Session, select
from websockets.asyncio.client import connect

from backend_core.migrations import _PUBLIC_REVISION, _TENANT_REVISION, _alembic_config
from dataforge_protocol import compute_pb2, enums_pb2
from tests.harness.postgres_harness import (
    BACKEND_ROOT,
    CORE_ROOT,
    SCHEDULER_ROOT,
    WORKER_ROOT,
    ManagedProcess,
    PostgresContainer,
    RustfsContainer,
    docker_env,
    docker_service_host,
    free_port,
    local_service_bind_address,
    process_host,
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


def _active_preview_request_with_lease(container: PostgresContainer) -> tuple[str, int, float] | None:
    with container.connect() as connection:
        row = connection.execute(
            'SELECT id, status, GREATEST(EXTRACT(EPOCH FROM (lease_expires_at - clock_timestamp())), 0) '
            'FROM "default".compute_requests WHERE kind = %s ORDER BY created_at DESC LIMIT 1',
            (enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,),
        ).fetchone()
    if row is None or row[1] not in {
        enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
        enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING,
    }:
        return None
    return str(row[0]), int(row[1]), float(row[2])


SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n'
INTERNAL_API_TOKEN = 'dataforge-runtime-test-internal-token'
ENGINE_TEST_IMAGE = 'data-forge-polars-engine:integration'


def _http_base_url(port: int) -> str:
    return f'http://{process_host()}:{port}'


def _websocket_url(port: int, path: str) -> str:
    return f'ws://{process_host()}:{port}{path}'


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
            'INTERNAL_GRPC_TARGET': f'{process_host()}:{target_port}',
            'RUNTIME_COORDINATOR_TARGET': f'{process_host()}:{target_port}',
            'WORKER_DATA_PLANE_GRPC_HOST': local_service_bind_address(),
            'WORKER_DATA_PLANE_GRPC_PORT': str(worker_data_plane_port),
            'WORKER_DATA_PLANE_GRPC_TARGET': f'{process_host()}:{worker_data_plane_port}',
        }
    )


def test_runtime_service_addresses_use_runner_and_docker_services(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv('TEST_PROCESS_HOST', '172.30.0.4')
    monkeypatch.setenv('TEST_DOCKER_SERVICE_HOST', 'docker')

    env = _runtime_env(
        data_dir=tmp_path,
        database_url='postgresql+psycopg://dataforge:dataforge@docker:54321/dataforge',
        port=8000,
        grpc_port=50051,
        data_plane_port=50052,
        rustfs=RustfsContainer(port=9000),
    )

    assert env['HOST'] == '0.0.0.0'
    assert env['INTERNAL_GRPC_TARGET'] == '172.30.0.4:50051'
    assert env['RUNTIME_COORDINATOR_TARGET'] == '172.30.0.4:50051'
    assert env['WORKER_DATA_PLANE_GRPC_TARGET'] == '172.30.0.4:50052'
    assert env['OBJECT_STORE_ENDPOINT'] == 'http://docker:9000'


@pytest.fixture(scope='module')
def engine_runtime_env(rustfs_container: RustfsContainer) -> Generator[dict[str, str]]:
    """Use the engine image built by the canonical test recipe before pytest starts."""
    require_docker()
    run_command(
        ['docker', 'image', 'inspect', ENGINE_TEST_IMAGE],
        cwd=CORE_ROOT,
        env=docker_env(),
    )
    docker_host = os.environ.get('DOCKER_HOST')
    if not docker_host:
        raise RuntimeError('DOCKER_HOST must identify the Docker service daemon')
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
            'ENGINE_CONNECT_HOST': docker_service_host(),
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


def _runtime_failure_context(container: PostgresContainer, **processes: ManagedProcess) -> str:
    with container.connect() as connection:
        requests = connection.execute(
            'SELECT id, kind, status, compute_worker_resource_id, lease_owner, attempts, error_message '
            'FROM "default".compute_requests ORDER BY created_at DESC LIMIT 5'
        ).fetchall()
        wakes = connection.execute(
            'SELECT namespace, kind, pending, generation, processed_generation FROM public.runtime_namespace_work ORDER BY namespace, kind'
        ).fetchall()
    engine_logs = ''
    if requests:
        request_id = str(requests[0][0])
        engine_name = f'dataforge-engine-default-{request_id[:15]}'
        containers = run_command(
            ['docker', 'ps', '-a', '--filter', f'name={engine_name}', '--format', '{{.ID}}'],
            env=docker_env(),
            check=False,
        ).stdout.splitlines()
        engine_logs = '\n'.join(run_command(['docker', 'logs', container_id], env=docker_env(), check=False).stdout for container_id in containers)
    tails = '\n'.join(f'{name} tail:\n{process.tail()}' for name, process in processes.items())
    return f'\nrecent compute requests: {requests!r}\nruntime work: {wakes!r}\nengine logs:\n{engine_logs}\n{tails}'


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


def _blocked_compute_terminal_publications(container: PostgresContainer, blocker_pid: int) -> list[tuple[int, str]]:
    with container.connect() as connection:
        rows = connection.execute(
            """
            WITH RECURSIVE blocking_chain(waiter_pid, blocker_pid, depth) AS (
                SELECT activity.pid, blocker.pid, 1
                FROM pg_stat_activity AS activity
                CROSS JOIN LATERAL unnest(pg_blocking_pids(activity.pid)) AS blocker(pid)
                WHERE activity.datname = current_database()
                UNION ALL
                SELECT blocking_chain.waiter_pid, blocker.pid, blocking_chain.depth + 1
                FROM blocking_chain
                CROSS JOIN LATERAL unnest(pg_blocking_pids(blocking_chain.blocker_pid)) AS blocker(pid)
                WHERE blocking_chain.depth < 8
            )
            SELECT activity.pid, activity.query
            FROM pg_stat_activity AS activity
            WHERE activity.wait_event_type = 'Lock'
              AND activity.query ILIKE 'SELECT%%compute_requests%%FOR UPDATE%%'
              AND EXISTS (
                  SELECT 1 FROM blocking_chain
                  WHERE blocking_chain.waiter_pid = activity.pid AND blocking_chain.blocker_pid = %s
              )
            """,
            (blocker_pid,),
        ).fetchall()
    return [(int(pid), str(query)) for pid, query in rows]


def _runtime_coordinator_lock_activity(container: PostgresContainer) -> list[tuple[object, ...]]:
    with container.connect() as connection:
        rows = connection.execute(
            """
            SELECT pid, application_name, client_addr, state, wait_event_type, wait_event,
                   client_port, xact_start, pg_blocking_pids(pid), query
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND (query ILIKE '%runtime_coordinator_state%' OR wait_event_type = 'Lock')
            ORDER BY backend_start
            """
        ).fetchall()
    return [tuple(row) for row in rows]


def _runtime_coordinator_processes() -> list[str]:
    result = subprocess.run(['ps', '-eo', 'pid=,ppid=,pgid=,sid=,stat=,args='], capture_output=True, check=True, text=True)
    return [line.strip() for line in result.stdout.splitlines() if '/runtime_coordinator.py' in line]


def _coordinator_database_sessions(container: PostgresContainer, application_name: str) -> list[int]:
    with container.connect() as connection:
        sessions = connection.execute(
            'SELECT pid FROM pg_stat_activity WHERE datname = current_database() AND application_name = %s AND pid <> pg_backend_pid()',
            (application_name,),
        ).fetchall()
    return [int(row[0]) for row in sessions]


def _terminate_coordinator_database_sessions(container: PostgresContainer, application_name: str) -> list[int]:
    with container.connect() as connection:
        sessions = connection.execute(
            'SELECT pid FROM pg_stat_activity WHERE datname = current_database() AND application_name = %s AND pid <> pg_backend_pid()',
            (application_name,),
        ).fetchall()
        pids = [int(row[0]) for row in sessions]
        for pid in pids:
            connection.execute('SELECT pg_terminate_backend(%s)', (pid,))
    return pids


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
            assert _table_exists(connection, 'public', 'compute_worker_instances')
            assert _table_exists(connection, 'public', 'runtime_namespace_work')
            assert _table_exists(connection, 'public', 'runtime_namespace_work_wakes')
            assert _table_exists(connection, 'public', 'runtime_coordinator_state')
            assert _query_value(connection, 'SELECT generation FROM public.runtime_coordinator_state WHERE singleton_id = 1') == 0
            assert _table_exists(connection, 'default', 'build_runs')
            assert _table_exists(connection, 'default', 'build_run_datasources')
            assert _table_exists(connection, 'default', 'build_jobs')
            assert _table_exists(connection, 'default', 'runtime_outbox_events')
            assert _table_exists(connection, 'default', 'notification_delivery_receipts')
            assert _table_exists(connection, 'default', 'notification_delivery_part_receipts')
            assert _table_exists(connection, 'alpha', 'build_runs')
            assert _table_exists(connection, 'alpha', 'build_run_datasources')
            assert _table_exists(connection, 'alpha', 'build_jobs')
            assert _table_exists(connection, 'alpha', 'runtime_outbox_events')
            assert _table_exists(connection, 'alpha', 'notification_delivery_receipts')
            assert _table_exists(connection, 'alpha', 'notification_delivery_part_receipts')
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


@pytest.mark.timeout(300)
def test_build_datasource_migration_backfills_nonterminal_pipeline_dependencies(monkeypatch) -> None:
    require_docker()

    from backend_core.config import settings

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        schema = f'build_deps_{uuid.uuid4().hex[:12]}'
        config = _alembic_config(scope='tenant', schema=schema)
        command.upgrade(config, '0018_runtime_work_generations', tag='tenant')
        build_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        request_json = {
            'analysis_pipeline': {
                'analysis_id': 'migration-analysis',
                'tabs': [
                    {
                        'id': 'tab-main',
                        'datasource': {'id': 'source-main', 'analysis_tab_id': None, 'source_type': 'file'},
                        'output': {'result_id': 'local-output'},
                        'steps': [
                            {'type': 'join', 'config': {'right_source': 'source-right'}},
                            {'type': 'union_by_name', 'config': {'sources': ['source-third', 'local-output', 'tab-derived']}},
                        ],
                    },
                    {
                        'id': 'tab-derived',
                        'datasource': {'id': 'local-output', 'analysis_tab_id': 'tab-main', 'source_type': 'analysis'},
                        'output': {'result_id': 'local-derived-output'},
                        'steps': [],
                    },
                ],
            },
            'tab_id': 'tab-main',
        }
        try:
            with container.connect() as connection:
                connection.execute(f'SET search_path TO "{schema}", public')
                connection.execute(
                    'INSERT INTO build_runs '
                    '(id, namespace, analysis_id, analysis_name, status, request_json, starter_json, '
                    'progress, elapsed_ms, total_steps, total_tabs, created_at, started_at, updated_at, '
                    'version, execution_generation, next_event_sequence) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 0, 1, %s, %s, %s, 1, 0, 1)',
                    (
                        build_id,
                        'legacy',
                        'migration-analysis',
                        'Migration analysis',
                        'queued',
                        Jsonb(request_json),
                        Jsonb({}),
                        now,
                        now,
                        now,
                    ),
                )

            command.upgrade(config, '0019_build_run_datasources', tag='tenant')
            with container.connect() as connection:
                dependencies = connection.execute(
                    f'SELECT namespace, datasource_id FROM "{schema}".build_run_datasources WHERE build_id = %s ORDER BY datasource_id',
                    (build_id,),
                ).fetchall()
                revision_row = connection.execute(f'SELECT version_num FROM "{schema}".alembic_version').fetchone()
                assert revision_row is not None
                revision = revision_row[0]
            assert dependencies == [('legacy', 'source-main'), ('legacy', 'source-right'), ('legacy', 'source-third')]
            assert revision == '0019_build_run_datasources'
        finally:
            with container.connect() as connection:
                connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.timeout(120)
def test_pivot_values_migration_rewrites_analysis_and_version_pipelines(monkeypatch) -> None:
    require_docker()

    from backend_core.config import settings

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        schema = f'pivot_values_{uuid.uuid4().hex[:12]}'
        config = _alembic_config(scope='tenant', schema=schema)
        command.upgrade(config, '0023_drop_ds_freshness', tag='tenant')
        now = datetime.now(UTC)
        analysis_pipeline = {
            'tabs': [
                {
                    'steps': [
                        {
                            'id': 'pivot-analysis',
                            'type': 'pivot',
                            'config': {'index': ['group'], 'columns': 'period', 'values': 'age'},
                        }
                    ]
                }
            ]
        }
        snapshot_pipeline = {
            'tabs': [
                {
                    'steps': [
                        {
                            'id': 'pivot-snapshot',
                            'type': 'pivot',
                            'config': {'index': ['group'], 'columns': 'period', 'values': None},
                        }
                    ]
                }
            ]
        }
        try:
            with container.connect() as connection:
                connection.execute(
                    f'INSERT INTO "{schema}".analyses '
                    '(id, name, pipeline_definition, status, created_at, updated_at, revision) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    ('legacy-pivot', 'Legacy pivot', Json(analysis_pipeline), 'draft', now, now, 1),
                )
                connection.execute(
                    f'INSERT INTO "{schema}".analysis_versions '
                    '(id, analysis_id, version, name, pipeline_definition, created_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s)',
                    ('legacy-pivot-v1', 'legacy-pivot', 1, 'Legacy pivot', Json(snapshot_pipeline), now),
                )

            command.upgrade(config, _TENANT_REVISION, tag='tenant')
            with container.connect() as connection:
                analysis_row = connection.execute(
                    f'SELECT pipeline_definition FROM "{schema}".analyses WHERE id = %s',
                    ('legacy-pivot',),
                ).fetchone()
                snapshot_row = connection.execute(
                    f'SELECT pipeline_definition FROM "{schema}".analysis_versions WHERE id = %s',
                    ('legacy-pivot-v1',),
                ).fetchone()
            assert analysis_row is not None and snapshot_row is not None
            analysis_config = analysis_row[0]['tabs'][0]['steps'][0]['config']
            snapshot_config = snapshot_row[0]['tabs'][0]['steps'][0]['config']
            assert analysis_config['value_columns'] == ['age']
            assert 'values' not in analysis_config
            assert snapshot_config['value_columns'] == []
            assert 'values' not in snapshot_config

            command.downgrade(config, '0023_drop_ds_freshness', tag='tenant')
            with container.connect() as connection:
                analysis_row = connection.execute(
                    f'SELECT pipeline_definition FROM "{schema}".analyses WHERE id = %s',
                    ('legacy-pivot',),
                ).fetchone()
                snapshot_row = connection.execute(
                    f'SELECT pipeline_definition FROM "{schema}".analysis_versions WHERE id = %s',
                    ('legacy-pivot-v1',),
                ).fetchone()
            assert analysis_row is not None and snapshot_row is not None
            assert analysis_row[0]['tabs'][0]['steps'][0]['config']['values'] == 'age'
            assert snapshot_row[0]['tabs'][0]['steps'][0]['config']['values'] is None
        finally:
            with container.connect() as connection:
                connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.timeout(180)
def test_compute_worker_instance_migration_preserves_rows_and_downgrades(monkeypatch) -> None:
    require_docker()

    from backend_core.config import settings

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        config = _alembic_config(scope='public', schema='public')
        command.upgrade(config, '0020_runtime_wakes', tag='public')
        now = datetime.now(UTC)
        with container.connect() as connection:
            connection.execute(
                'INSERT INTO public.engine_instances '
                '(id, worker_id, namespace, analysis_id, engine_scope, engine_reuse_policy, status, '
                'current_engine_run_id, last_seen_at, updated_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                ('instance-1', 'worker-1', 'default', 'analysis-1', 'analysis_interactive', 'shared', 'idle', 'run-1', now, now),
            )
            connection.commit()

        command.upgrade(config, _PUBLIC_REVISION, tag='public')
        with container.connect() as connection:
            row = connection.execute(
                'SELECT compute_worker_scope, compute_worker_reuse_policy, current_compute_worker_run_id FROM public.compute_worker_instances WHERE id = %s',
                ('instance-1',),
            ).fetchone()
            index_names = {
                index[0]
                for index in connection.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'compute_worker_instances'"
                ).fetchall()
            }
            constraint_names = {
                constraint[0]
                for constraint in connection.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid = 'public.compute_worker_instances'::regclass"
                ).fetchall()
            }
        assert row == ('analysis_interactive', 'shared', 'run-1')
        assert {
            'compute_worker_instances_pkey',
            'ix_compute_worker_instances_worker_id',
            'ix_compute_worker_instances_namespace',
            'ix_compute_worker_instances_analysis_id',
            'ix_compute_worker_instances_compute_worker_scope',
            'ix_compute_worker_instances_status',
            'ix_compute_worker_instances_last_seen_at',
        } == index_names
        assert 'compute_worker_instances_pkey' in constraint_names
        assert not any('engine' in name for name in index_names | constraint_names)

        command.downgrade(config, '0020_runtime_wakes', tag='public')
        with container.connect() as connection:
            row = connection.execute(
                'SELECT engine_scope, engine_reuse_policy, current_engine_run_id FROM public.engine_instances WHERE id = %s',
                ('instance-1',),
            ).fetchone()
            index_names = {
                index[0]
                for index in connection.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'engine_instances'").fetchall()
            }
            constraint_names = {
                constraint[0]
                for constraint in connection.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'public.engine_instances'::regclass").fetchall()
            }
        assert row == ('analysis_interactive', 'shared', 'run-1')
        assert 'engine_instances_pkey' in index_names
        assert 'engine_instances_pkey' in constraint_names
        assert 'ix_engine_instances_engine_scope' in index_names


@pytest.mark.timeout(180)
def test_compute_worker_tenant_migration_preserves_rows_and_downgrades(monkeypatch) -> None:
    require_docker()

    from backend_core.config import settings

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        schema = f'worker_rename_{uuid.uuid4().hex[:12]}'
        config = _alembic_config(scope='tenant', schema=schema)
        command.upgrade(config, '0024_pivot_value_columns', tag='tenant')
        now = datetime.now(UTC)
        try:
            with container.connect() as connection:
                connection.execute(
                    f'INSERT INTO "{schema}".engine_runs '
                    '(id, namespace, datasource_id, kind, status, request_json, created_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    ('run-1', 'default', 'source-1', 'preview', 'completed', Jsonb({'input': 'kept'}), now),
                )
                connection.execute(
                    f'INSERT INTO "{schema}".compute_requests '
                    '(id, namespace, kind, status, engine_scope, engine_reuse_policy, engine_resource_id, '
                    'command_envelope, created_at, updated_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    ('request-1', 'default', 1, 1, 2, 1, 'analysis-1', b'command', now, now),
                )
                connection.execute(
                    f'INSERT INTO "{schema}".build_runs '
                    '(id, namespace, analysis_id, analysis_name, status, request_json, starter_json, '
                    'current_engine_run_id, created_at, started_at, updated_at, execution_generation, next_event_sequence) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    ('build-1', 'default', 'analysis-1', 'Analysis', 'running', Jsonb({}), Jsonb({}), 'run-1', now, now, now, 1, 1),
                )
                connection.execute(
                    f'INSERT INTO "{schema}".build_events '
                    '(id, build_id, namespace, sequence, type, payload_json, engine_run_id, emitted_at, created_at) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    ('event-1', 'build-1', 'default', 1, 'progress', Jsonb({'progress': 0.5}), 'run-1', now, now),
                )
                connection.commit()

            command.upgrade(config, _TENANT_REVISION, tag='tenant')
            with container.connect() as connection:
                run_row = connection.execute(
                    f'SELECT namespace, datasource_id, kind, status, request_json FROM "{schema}".compute_worker_runs WHERE id = %s',
                    ('run-1',),
                ).fetchone()
                request_row = connection.execute(
                    f'SELECT compute_worker_scope, compute_worker_reuse_policy, compute_worker_resource_id, command_envelope '
                    f'FROM "{schema}".compute_requests WHERE id = %s',
                    ('request-1',),
                ).fetchone()
                build_run_id = connection.execute(
                    f'SELECT current_compute_worker_run_id FROM "{schema}".build_runs WHERE id = %s',
                    ('build-1',),
                ).fetchone()
                event_run_id = connection.execute(
                    f'SELECT compute_worker_run_id FROM "{schema}".build_events WHERE id = %s',
                    ('event-1',),
                ).fetchone()
                index_names = {
                    index[0]
                    for index in connection.execute(
                        'SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename IN '
                        "('compute_worker_runs', 'compute_requests', 'build_runs', 'build_events')",
                        (schema,),
                    ).fetchall()
                }
                constraint_names = {
                    constraint[0]
                    for constraint in connection.execute(
                        'SELECT c.conname FROM pg_constraint AS c '
                        'JOIN pg_class AS t ON t.oid = c.conrelid '
                        'JOIN pg_namespace AS n ON n.oid = t.relnamespace '
                        "WHERE n.nspname = %s AND t.relname IN ('compute_worker_runs', 'compute_requests', 'build_runs', 'build_events')",
                        (schema,),
                    ).fetchall()
                }
            assert run_row == ('default', 'source-1', 'preview', 'completed', {'input': 'kept'})
            assert request_row == (2, 1, 'analysis-1', b'command')
            assert build_run_id == ('run-1',)
            assert event_run_id == ('run-1',)
            assert {
                'ix_compute_worker_runs_namespace',
                'ix_compute_requests_compute_worker_identity',
                'ix_build_runs_current_compute_worker_run_id',
                'ix_build_events_compute_worker_run_id',
            } <= index_names
            assert 'compute_worker_runs_pkey' in index_names
            assert 'compute_worker_runs_pkey' in constraint_names
            assert not any('engine' in name for name in index_names | constraint_names)

            command.downgrade(config, '0024_pivot_value_columns', tag='tenant')
            with container.connect() as connection:
                run_row = connection.execute(
                    f'SELECT namespace, datasource_id, kind, status, request_json FROM "{schema}".engine_runs WHERE id = %s',
                    ('run-1',),
                ).fetchone()
                request_row = connection.execute(
                    f'SELECT engine_scope, engine_reuse_policy, engine_resource_id, command_envelope FROM "{schema}".compute_requests WHERE id = %s',
                    ('request-1',),
                ).fetchone()
                build_run_id = connection.execute(
                    f'SELECT current_engine_run_id FROM "{schema}".build_runs WHERE id = %s',
                    ('build-1',),
                ).fetchone()
                event_run_id = connection.execute(
                    f'SELECT engine_run_id FROM "{schema}".build_events WHERE id = %s',
                    ('event-1',),
                ).fetchone()
                index_names = {
                    index[0]
                    for index in connection.execute(
                        'SELECT indexname FROM pg_indexes WHERE schemaname = %s',
                        (schema,),
                    ).fetchall()
                }
                constraint_names = {
                    constraint[0]
                    for constraint in connection.execute(
                        'SELECT c.conname FROM pg_constraint AS c '
                        'JOIN pg_class AS t ON t.oid = c.conrelid '
                        'JOIN pg_namespace AS n ON n.oid = t.relnamespace '
                        "WHERE n.nspname = %s AND t.relname = 'engine_runs'",
                        (schema,),
                    ).fetchall()
                }
            assert run_row == ('default', 'source-1', 'preview', 'completed', {'input': 'kept'})
            assert request_row == (2, 1, 'analysis-1', b'command')
            assert build_run_id == ('run-1',)
            assert event_run_id == ('run-1',)
            assert 'engine_runs_pkey' in index_names
            assert 'engine_runs_pkey' in constraint_names
            assert {
                'ix_engine_runs_namespace',
                'ix_compute_requests_engine_identity',
                'ix_build_runs_current_engine_run_id',
                'ix_build_events_engine_run_id',
            } <= index_names
        finally:
            with container.connect() as connection:
                connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.mark.timeout(180)
def test_storage_cleanup_catalog_migration_backfills_indexes_and_downgrades(monkeypatch) -> None:
    require_docker()

    from backend_core.config import settings

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        schema = f'cleanup_catalog_{uuid.uuid4().hex[:12]}'
        config = _alembic_config(scope='tenant', schema=schema)
        command.upgrade(config, '0019_build_run_datasources', tag='tenant')
        now = datetime.now(UTC)
        event_id = str(uuid.uuid4())
        payload = {
            'resource_id': 'source-rid',
            'owner_kind': 'datasource',
            'owner_id': 'source-rid',
            'url': 's3://default/exports/source-rid',
            'is_prefix': True,
            'catalog_namespace': 'outputs',
            'catalog_table': 'source-rid_main_rev1',
            'catalog_family_prefix': 'source-rid_',
            'phase': 'tracked',
        }
        try:
            with container.connect() as connection:
                connection.execute(
                    f'INSERT INTO "{schema}".runtime_outbox_events '
                    '(id, kind, status, payload_json, attempts, lease_generation, available_at, created_at, updated_at) '
                    'VALUES (%s, %s, %s, %s, 0, 0, %s, %s, %s)',
                    (event_id, 'storage_cleanup', 'pending', Jsonb(payload), now, now, now),
                )

            command.upgrade(config, '0021_cleanup_catalog_idx', tag='tenant')
            with container.connect() as connection:
                identity = connection.execute(
                    f'SELECT catalog_namespace, catalog_table, catalog_family_prefix FROM "{schema}".runtime_outbox_events WHERE id = %s',
                    (event_id,),
                ).fetchone()
                indexes = {
                    row[0]
                    for row in connection.execute(
                        'SELECT indexname FROM pg_indexes WHERE schemaname = %s',
                        (schema,),
                    ).fetchall()
                }
                version_row = connection.execute(f'SELECT version_num FROM "{schema}".alembic_version').fetchone()

            assert version_row is not None
            assert identity == ('outputs', 'source-rid_main_rev1', 'source-rid_')
            assert {'ix_runtime_outbox_catalog_table', 'ix_runtime_outbox_catalog_family'} <= indexes
            assert version_row[0] == '0021_cleanup_catalog_idx'

            command.upgrade(config, '0022_telegram_part_receipts', tag='tenant')
            with container.connect() as connection:
                has_part_receipts = _table_exists(connection, schema, 'notification_delivery_part_receipts')
                version_row = connection.execute(f'SELECT version_num FROM "{schema}".alembic_version').fetchone()
            assert has_part_receipts
            assert version_row is not None
            assert version_row[0] == '0022_telegram_part_receipts'

            command.upgrade(config, _TENANT_REVISION, tag='tenant')
            with container.connect() as connection:
                datasource_columns = {
                    row[0]
                    for row in connection.execute(
                        'SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s',
                        (schema, 'datasources'),
                    ).fetchall()
                }
                version_row = connection.execute(f'SELECT version_num FROM "{schema}".alembic_version').fetchone()
            assert 'freshness_threshold_minutes' not in datasource_columns
            assert version_row is not None
            assert version_row[0] == _TENANT_REVISION

            command.downgrade(config, '0019_build_run_datasources', tag='tenant')
            with container.connect() as connection:
                columns = {
                    row[0]
                    for row in connection.execute(
                        'SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s',
                        (schema, 'runtime_outbox_events'),
                    ).fetchall()
                }
                version_row = connection.execute(f'SELECT version_num FROM "{schema}".alembic_version').fetchone()
            assert version_row is not None
            assert not {'catalog_namespace', 'catalog_table', 'catalog_family_prefix'} & columns
            assert version_row[0] == '0019_build_run_datasources'
        finally:
            with container.connect() as connection:
                connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


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

        # Downgrade the public schema as Alembic would, preserving tenant work
        # while removing every public object introduced after this revision.
        command.downgrade(_alembic_config(scope='public', schema='public'), '0001_runtime_public', tag='public')

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
            assert (
                _query_value(
                    connection,
                    'SELECT pending FROM public.runtime_namespace_work WHERE namespace = %s AND kind = %s',
                    ('default', 'outbox'),
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
def test_terminal_scheduled_build_reconciles_after_event_commit_without_holding_build_lock(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import build_jobs_service, build_runs_service, database, runtime_work_service
    from backend_core.build_commands import BuildClaimCommand, fail_build_job
    from backend_core.config import settings
    from backend_core.domain.build_runs.models import BuildRunStatus
    from backend_core.domain.compute.schemas import BuildFailedEvent
    from backend_core.persistence.scheduler.models import Schedule
    from modules.scheduler.service import reconcile_pending_schedule_runs

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
        schedule_id = 'schedule-terminal-race'
        build_id = 'build-terminal-race'
        worker_id = 'build-worker-terminal-race'
        with Session(database._get_tenant_engine()) as session:
            session.add(
                Schedule(
                    id=schedule_id,
                    datasource_id='source-datasource',
                    cron_expression='* * * * *',
                    enabled=True,
                    lease_owner='scheduler:test',
                    claim_token='schedule-claim-terminal-race',
                    lease_generation=1,
                    lease_expires_at=now + timedelta(minutes=5),
                    last_triggered_at=now,
                    created_at=now,
                )
            )
            build_runs_service.stage_build_run(
                session,
                build_id=build_id,
                namespace='default',
                schedule_id=schedule_id,
                analysis_id='analysis-terminal-race',
                analysis_name='Analysis',
                request_json={'analysis_pipeline': {'analysis_id': 'analysis-terminal-race', 'tabs': []}, 'tab_id': None},
                starter_json={'triggered_by': f'schedule:{schedule_id}'},
                status=BuildRunStatus.RUNNING,
                execution_generation=1,
                created_at=now,
                started_at=now,
            )
            session.commit()
            build_jobs_service.stage_job(session, build_id=build_id, namespace='default')
            session.commit()
            claimed = build_jobs_service.claim_next_job(session, worker_id=worker_id)
            assert claimed is not None
            claim = BuildClaimCommand(
                job_id=claimed.id,
                build_id=build_id,
                worker_id=worker_id,
                claim_token=claimed.claim_token or '',
                lease_generation=claimed.lease_generation,
            )

        schedule_lock = Session(database._get_tenant_engine())
        schedule_lock.execute(text('SELECT id FROM schedules WHERE id = :id FOR UPDATE'), {'id': schedule_id})
        failure_done = threading.Event()
        failure_results: list[object] = []
        failure_errors: list[BaseException] = []

        def fail_in_independent_session() -> None:
            try:
                with Session(database._get_tenant_engine()) as session:
                    session.execute(text("SET LOCAL lock_timeout = '3s'"))
                    failure_results.append(fail_build_job(session, claim, error='integration failure'))
            except BaseException as exc:
                failure_errors.append(exc)
            finally:
                failure_done.set()

        failure_thread = threading.Thread(target=fail_in_independent_session, name='terminal-build-failure')
        failure_thread.start()
        try:
            assert failure_done.wait(timeout=5), 'terminal transition waited on schedule reconciliation while holding BuildRun'
            failure_thread.join(timeout=1)
            assert not failure_errors, failure_errors
            assert failure_results and failure_results[0] is not None

            # The schedule row remains locked to simulate slow reconciliation.
            # A subsequent event for this terminal build must still commit.
            with Session(database._get_tenant_engine()) as session:
                appended = build_runs_service.append_build_event(
                    session,
                    build_id=build_id,
                    event=BuildFailedEvent(
                        build_id=build_id,
                        analysis_id='analysis-terminal-race',
                        emitted_at=datetime.now(UTC),
                        progress=0,
                        elapsed_ms=0,
                        total_steps=0,
                        tabs_built=0,
                        results=[],
                        duration_ms=0,
                        error='integration failure replay',
                    ),
                )
                assert appended is not None
            with Session(database._get_tenant_engine()) as session:
                assert runtime_work_service.list_due_schedule_namespaces(session)
        finally:
            schedule_lock.rollback()
            schedule_lock.close()
            failure_thread.join(timeout=5)

        with Session(database._get_tenant_engine()) as session:
            assert reconcile_pending_schedule_runs(session, namespace='default') == 1
            schedule = session.get(Schedule, schedule_id)
            assert schedule is not None
            assert schedule.lease_owner is None
            assert schedule.claim_token is None
            assert schedule.last_failure_at is not None
            assert reconcile_pending_schedule_runs(session, namespace='default') == 0

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
            first = runtime_work_service.list_due_schedule_namespaces(session)
            assert len(first) == 1
            namespace, generation, first_wake_ids = first[0]
            assert namespace == 'default' and first_wake_ids

            # A producer commits after this pass captured its exact wake IDs.
            runtime_work_service.mark_schedule_pending(session, namespace='default')
            session.commit()
            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=generation,
                due_at=due_at,
                wake_ids=first_wake_ids,
            )
            session.commit()

            second = runtime_work_service.list_due_schedule_namespaces(session)
            assert len(second) == 1
            namespace, generation, second_wake_ids = second[0]
            assert namespace == 'default' and second_wake_ids
            assert set(first_wake_ids).isdisjoint(second_wake_ids)

            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=generation,
                due_at=due_at,
                wake_ids=second_wake_ids,
            )
            session.commit()
            assert runtime_work_service.list_due_schedule_namespaces(session) == []

            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=generation + 1,
                due_at=datetime.now(UTC) - timedelta(seconds=1),
            )
            session.commit()
            due = runtime_work_service.list_due_schedule_namespaces(session)
            assert len(due) == 1 and due[0][0] == 'default' and due[0][2] == []

        _clear_database_state()


@pytest.mark.timeout(300)
def test_runtime_wake_migration_recreates_journal_and_preserves_markers(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core.config import settings

    with PostgresContainer() as container:
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        config = _alembic_config(scope='public', schema='public')
        command.upgrade(config, '0018_runtime_work_generations')

        marker_due_at = datetime.now(UTC) + timedelta(minutes=10)
        with container.connect() as connection:
            connection.execute(
                """
                INSERT INTO public.runtime_namespace_work
                    (namespace, kind, pending, generation, processed_generation, due_at, updated_at)
                VALUES ('alpha', 'compute', TRUE, 17, 12, %s, statement_timestamp())
                """,
                (marker_due_at,),
            )
            connection.commit()
            assert not _table_exists(connection, 'public', 'runtime_namespace_work_wakes')

        command.upgrade(config, _PUBLIC_REVISION)
        with container.connect() as connection:
            assert _table_exists(connection, 'public', 'runtime_namespace_work_wakes')
            marker = connection.execute(
                """
                SELECT pending, generation, processed_generation, due_at
                FROM public.runtime_namespace_work
                WHERE namespace = 'alpha' AND kind = 'compute'
                """
            ).fetchone()
            assert marker == (True, 17, 12, marker_due_at)
            index_names = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = 'runtime_namespace_work_wakes'
                    """
                ).fetchall()
            }
            assert {
                'ix_runtime_namespace_work_wakes_kind_namespace_id',
                'ix_runtime_namespace_work_wakes_namespace_kind_id',
            } <= index_names


@pytest.mark.timeout(300)
def test_runtime_wake_appends_do_not_wait_for_marker_lock(monkeypatch, tmp_path: Path) -> None:
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

        from backend_core.persistence.runtime_events.models import RuntimeNamespaceWork

        engine = database._get_tenant_engine()
        with Session(engine) as setup:
            setup.add(
                RuntimeNamespaceWork(
                    namespace='default',
                    kind=runtime_work_service.RuntimeWorkKind.OUTBOX.value,
                    pending=False,
                    generation=0,
                    processed_generation=0,
                    due_at=None,
                    updated_at=datetime.now(UTC),
                )
            )
            setup.commit()

        append_durations_ms: list[float] = []
        append_errors: list[BaseException] = []
        appends_finished = threading.Event()

        def produce_wakes(producer_number: int) -> None:
            try:
                with Session(engine) as producer:
                    for _ in range(25):
                        started = time.perf_counter()
                        runtime_work_service.append_wake(
                            producer,
                            namespace='default',
                            kind=runtime_work_service.RuntimeWorkKind.OUTBOX,
                        )
                        append_durations_ms.append((time.perf_counter() - started) * 1000)
                    producer.commit()
            except BaseException as exc:
                append_errors.append(exc)
            finally:
                if producer_number == 3:
                    appends_finished.set()

        with Session(engine) as marker_lock:
            marker_lock.execute(text("SELECT namespace FROM public.runtime_namespace_work WHERE namespace = 'default' AND kind = 'outbox' FOR UPDATE")).one()
            producers = [threading.Thread(target=produce_wakes, args=(index,)) for index in range(4)]
            for producer_thread in producers:
                producer_thread.start()
            completed_while_locked = appends_finished.wait(timeout=3)
            for producer_thread in producers:
                producer_thread.join(timeout=1)
            assert completed_while_locked, 'append-only producers waited behind the held namespace marker lock'
            assert not append_errors
            assert len(append_durations_ms) == 100
            measured_max_ms = max(append_durations_ms)
            print(f'100 concurrent outbox wake appends under held marker lock: max={measured_max_ms:.2f}ms')
            assert measured_max_ms < 1000, f'wake append unexpectedly stalled under marker lock: {measured_max_ms:.1f}ms'

        with Session(engine) as session:
            runtime_work_service.append_wake(session, namespace='alpha', kind=runtime_work_service.RuntimeWorkKind.BUILD)
            session.commit()
            assert runtime_work_service.list_pending_namespaces(session, kinds=[runtime_work_service.RuntimeWorkKind.OUTBOX]) == ['default']
            assert runtime_work_service.list_pending_namespaces(session, kinds=[runtime_work_service.RuntimeWorkKind.BUILD]) == ['alpha']
            assert (
                session.execute(text("SELECT count(*) FROM public.runtime_namespace_work_wakes WHERE namespace = 'default' AND kind = 'outbox'")).scalar_one()
                == 100
            )

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
            due = runtime_work_service.list_due_schedule_namespaces(session)
            assert len(due) == 1 and due[0][0] == 'default' and due[0][1] == 0
            first_wake_id = due[0][2][0]

            runtime_work_service.mark_schedule_pending(session, namespace='default')
            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=0,
                due_at=due_at,
                wake_ids=[first_wake_id],
            )
            session.commit()
            due = runtime_work_service.list_due_schedule_namespaces(session)
            assert len(due) == 1 and due[0][0] == 'default' and due[0][1] == 1
            second_wake_id = due[0][2][0]

            runtime_work_service.finish_schedule_scan(
                session,
                namespace='default',
                generation=1,
                due_at=due_at,
                wake_ids=[second_wake_id],
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
            due = runtime_work_service.list_due_schedule_namespaces(session)
            assert len(due) == 1 and due[0][0] == 'default' and due[0][1] == 3 and due[0][2] == []

        # Sequence allocation is not commit order: the lower ID remains
        # discoverable when a consumer acknowledges only the captured higher ID.
        low_id_producer = Session(database._get_tenant_engine())
        low_id = runtime_work_service.append_wake(
            low_id_producer,
            namespace='alpha',
            kind=runtime_work_service.RuntimeWorkKind.SCHEDULE,
        )
        assert low_id is not None
        with Session(database._get_tenant_engine()) as high_id_producer:
            high_id = runtime_work_service.append_wake(
                high_id_producer,
                namespace='alpha',
                kind=runtime_work_service.RuntimeWorkKind.SCHEDULE,
            )
            assert high_id is not None
            high_id_producer.commit()
        with Session(database._get_tenant_engine()) as consumer:
            captured = runtime_work_service.list_due_schedule_namespaces(consumer)
            alpha = next(item for item in captured if item[0] == 'alpha')
            assert alpha[2] == [high_id] and high_id > low_id
            captured_high_id = alpha[2]
        low_id_producer.commit()
        low_id_producer.close()
        with Session(database._get_tenant_engine()) as consumer:
            runtime_work_service.finish_schedule_scan(
                consumer,
                namespace='alpha',
                generation=0,
                due_at=due_at,
                wake_ids=captured_high_id,
            )
            consumer.commit()
            remaining = runtime_work_service.list_due_schedule_namespaces(consumer)
            alpha = next(item for item in remaining if item[0] == 'alpha')
            assert alpha[2] == [low_id]

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

            assert compute_requests_service.reconcile_expired_requests(session, namespace='default') == 0
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

            assert compute_requests_service.reconcile_expired_requests(session, namespace='default') == 1
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
            session.execute(text("DELETE FROM public.runtime_namespace_work_wakes WHERE namespace = 'default' AND kind = 'compute'"))
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
        with Session(database._get_tenant_engine()) as session:
            generation_before_race = int(
                session.execute(text("SELECT generation FROM public.runtime_namespace_work WHERE namespace = 'default' AND kind = 'compute'")).scalar_one()
            )
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
            marker = session.execute(
                text("SELECT pending, generation FROM public.runtime_namespace_work WHERE namespace = 'default' AND kind = 'compute'")
            ).one()
            assert marker.pending is False, 'the older snapshot should not claim unseen work as part of its projection'
            assert marker.generation > generation_before_race
            assert runtime_work_service.list_pending_namespaces(session) == ['default']
            assert (
                session.execute(text("SELECT count(*) FROM public.runtime_namespace_work_wakes WHERE namespace = 'default' AND kind = 'compute'")).scalar_one()
                == 1
            ), 'wake committed after capture was acknowledged by the older refresh'
            assert session.get(ComputeRequest, 'enqueue-during-refresh') is not None

        _clear_database_state()


@pytest.mark.timeout(300)
def test_refresh_missing_runtime_work_marker_does_not_block_producer(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database, runtime_work_service
    from backend_core.config import settings
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

        kind = runtime_work_service.RuntimeWorkKind.COMPUTE
        gate_key = int.from_bytes(uuid.uuid4().bytes[:8], 'big', signed=True)
        pending_query = f"""
            WITH gate AS MATERIALIZED (
                SELECT pg_advisory_xact_lock_shared({gate_key})
            )
            SELECT 1 FROM gate WHERE random() < 0
        """
        refresh_pid: list[int] = []
        refresh_started = threading.Event()
        refresh_finished = threading.Event()
        refresh_errors: list[BaseException] = []
        producer_finished = threading.Event()
        producer_errors: list[BaseException] = []
        now = datetime.now(UTC)

        def refresh_missing_marker() -> None:
            try:
                with Session(database._get_tenant_engine()) as session:
                    refresh_pid.append(int(session.execute(text('SELECT pg_backend_pid()')).scalar_one()))
                    refresh_started.set()
                    runtime_work_service.refresh_pending_work(
                        session,
                        namespace='default',
                        kind=kind,
                        pending_query=pending_query,
                    )
                    session.commit()
            except BaseException as exc:
                refresh_errors.append(exc)
            finally:
                refresh_finished.set()

        def enqueue_work_during_snapshot() -> None:
            try:
                with Session(database._get_tenant_engine()) as session:
                    session.add(
                        ComputeRequest(
                            id='enqueue-during-missing-marker-refresh',
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
                    session.flush()
                    runtime_work_service.append_wake(session, namespace='default', kind=kind)
                    session.commit()
            except BaseException as exc:
                producer_errors.append(exc)
            finally:
                producer_finished.set()

        with container.connect() as gate_connection:
            gate_connection.execute('SELECT pg_advisory_lock(%s)', (gate_key,))
            refresh_thread = threading.Thread(target=refresh_missing_marker)
            producer_thread = threading.Thread(target=enqueue_work_during_snapshot)
            gate_released = False
            try:
                with Session(database._get_tenant_engine()) as session:
                    session.execute(
                        text('DELETE FROM public.runtime_namespace_work WHERE namespace = :namespace AND kind = :kind'),
                        {'namespace': 'default', 'kind': kind.value},
                    )
                    session.execute(
                        text('DELETE FROM public.runtime_namespace_work_wakes WHERE namespace = :namespace AND kind = :kind'),
                        {'namespace': 'default', 'kind': kind.value},
                    )
                    session.commit()
                with container.connect() as observer:
                    assert (
                        observer.execute(
                            'SELECT 1 FROM public.runtime_namespace_work WHERE namespace = %s AND kind = %s',
                            ('default', kind.value),
                        ).fetchone()
                        is None
                    )

                refresh_thread.start()
                assert refresh_started.wait(timeout=5), 'refresh did not start its queue snapshot'
                scanning = False
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with container.connect() as observer:
                        activity = observer.execute(
                            'SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE pid = %s',
                            (refresh_pid[0],),
                        ).fetchone()
                    if activity == ('Lock', 'advisory'):
                        scanning = True
                        break
                    time.sleep(0.01)
                assert scanning, 'queue snapshot did not block on the advisory-lock gate'

                producer_thread.start()
                assert producer_finished.wait(timeout=2), 'producer blocked behind refresh initialization or snapshot'
                producer_thread.join(timeout=1)
                assert not producer_thread.is_alive()
                assert not producer_errors
                assert not refresh_finished.is_set(), 'refresh passed the still-held queue-snapshot gate'

                with container.connect() as observer:
                    marker = observer.execute(
                        'SELECT pending, generation FROM public.runtime_namespace_work WHERE namespace = %s AND kind = %s',
                        ('default', kind.value),
                    ).fetchone()
                assert marker is None, 'producer unexpectedly touched the namespace marker'
                with container.connect() as observer:
                    assert observer.execute(
                        'SELECT count(*) FROM public.runtime_namespace_work_wakes WHERE namespace = %s AND kind = %s',
                        ('default', kind.value),
                    ).fetchone() == (1,)

                gate_connection.execute('SELECT pg_advisory_unlock(%s)', (gate_key,))
                gate_released = True
                refresh_thread.join(timeout=10)
                assert not refresh_thread.is_alive(), 'refresh did not finish after releasing the gate'
                assert not refresh_errors
                with Session(database._get_tenant_engine()) as session:
                    final_marker = session.execute(
                        text(
                            'SELECT pending, generation, processed_generation FROM public.runtime_namespace_work WHERE namespace = :namespace AND kind = :kind'
                        ),
                        {'namespace': 'default', 'kind': kind.value},
                    ).one()
                    assert final_marker == (False, 1, 1), 'queue snapshot should not claim a post-capture enqueue'
                    assert runtime_work_service.list_pending_namespaces(session, kinds=[kind]) == ['default']
                    assert session.get(ComputeRequest, 'enqueue-during-missing-marker-refresh') is not None
            finally:
                if not gate_released:
                    gate_connection.execute('SELECT pg_advisory_unlock(%s)', (gate_key,))
                if producer_thread.ident is not None:
                    producer_thread.join(timeout=10)
                if refresh_thread.ident is not None:
                    refresh_thread.join(timeout=10)

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
                compute_worker_scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
                compute_worker_reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
                compute_worker_resource_id='analysis-shared-identity',
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
def test_postgres_busy_engine_claim_does_not_block_other_identity(monkeypatch, tmp_path: Path) -> None:
    """A held same-RID advisory lock must not pin a claim ahead of other RIDs."""
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
        database.set_active_runtime_coordinator_generation(None)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        namespace_token = set_namespace_context('default')
        gate_connection = None
        gate_held = False
        lock_key: int | None = None
        claim_thread: threading.Thread | None = None
        claim_done = threading.Event()
        claim_started = threading.Event()
        claim_result: list[ComputeRequest | None] = []
        claim_errors: list[BaseException] = []
        try:
            now = datetime.now(UTC)
            busy_requests = [
                ComputeRequest(
                    id=request_id,
                    namespace='default',
                    kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                    status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
                    compute_worker_scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
                    compute_worker_reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
                    compute_worker_resource_id='analysis-busy',
                    command_envelope=b'{}',
                    attempts=0,
                    max_attempts=3,
                    created_at=now + timedelta(microseconds=index),
                    updated_at=now,
                )
                for index, request_id in enumerate(('claim-busy-first', 'claim-busy-follower'))
            ]
            other_request = ComputeRequest(
                id='claim-other-rid',
                namespace='default',
                kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                status=enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED,
                compute_worker_scope=enums_pb2.COMPUTE_WORKER_SCOPE_ANALYSIS_INTERACTIVE,
                compute_worker_reuse_policy=enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED,
                compute_worker_resource_id='analysis-other',
                command_envelope=b'{}',
                attempts=0,
                max_attempts=3,
                created_at=now + timedelta(seconds=1),
                updated_at=now,
            )
            busy_request_ids = tuple(request.id for request in busy_requests)
            other_request_id = other_request.id
            with Session(database._get_tenant_engine()) as session:
                session.add_all([*busy_requests, other_request])
                session.commit()
                lock_key = compute_requests_service._engine_claim_lock_key(busy_requests[0])
            assert lock_key is not None

            gate_connection = container.connect()
            lock_result = gate_connection.execute('SELECT pg_try_advisory_lock(%s)', (lock_key,)).fetchone()
            assert lock_result is not None
            gate_held = bool(lock_result[0])
            assert gate_held, 'test could not acquire the same-RID engine claim lock'

            def claim_other_work() -> None:
                token = set_namespace_context('default')
                claim_started.set()
                try:
                    with Session(database._get_tenant_engine()) as session:
                        claim_result.append(compute_requests_service.claim_next_request(session, worker_id='worker-other'))
                except BaseException as exc:
                    claim_errors.append(exc)
                finally:
                    reset_namespace(token)
                    claim_done.set()

            claim_thread = threading.Thread(target=claim_other_work, name='claim-other-engine-rid')
            claim_thread.start()
            assert claim_started.wait(timeout=3)
            assert claim_done.wait(timeout=5), 'same-RID advisory lock blocked an eligible different-RID claim'
            assert not claim_errors, claim_errors
            assert len(claim_result) == 1
            assert claim_result[0] is not None and claim_result[0].id == other_request_id

            with Session(database._get_tenant_engine()) as session:
                persisted_busy = [session.get(ComputeRequest, request_id) for request_id in busy_request_ids]
                persisted_other = session.get(ComputeRequest, other_request_id)
            assert all(request is not None for request in persisted_busy)
            assert all(request.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED for request in persisted_busy if request is not None)
            assert persisted_other is not None and persisted_other.status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING

            gate_connection.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
            gate_held = False
            claim_thread.join(timeout=5)
            assert not claim_thread.is_alive()

            with Session(database._get_tenant_engine()) as session:
                claimed_busy = compute_requests_service.claim_next_request(session, worker_id='worker-after-release')
                assert claimed_busy is not None and claimed_busy.id == busy_request_ids[0]
                persisted_busy = [session.get(ComputeRequest, request_id) for request_id in busy_request_ids]
            statuses = [request.status for request in persisted_busy if request is not None]
            assert statuses.count(enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING) == 1
            assert statuses.count(enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED) == 1
        finally:
            if gate_held and gate_connection is not None and lock_key is not None:
                gate_connection.execute('SELECT pg_advisory_unlock(%s)', (lock_key,))
            if gate_connection is not None:
                gate_connection.close()
            if claim_thread is not None:
                claim_thread.join(timeout=10)
            reset_namespace(namespace_token)
            _clear_database_state()


@pytest.mark.timeout(300)
def test_postgres_shared_flight_followers_do_not_block_completion(monkeypatch, tmp_path: Path) -> None:
    """Active and cached follower reads must not retain row locks until HTTP commit."""
    require_docker()

    from backend_core import compute_requests_service, database
    from backend_core.config import settings
    from backend_core.domain.compute_requests.models import command_from_payload
    from backend_core.namespace import reset_namespace, set_namespace_context
    from backend_core.persistence.compute_requests.models import ComputeRequest, ComputeRequestFlight
    from backend_core.persistence.datasource.models import DataSource

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, 'database_url', container.url, raising=False)
        monkeypatch.setattr(settings, 'data_dir', data_dir, raising=False)
        monkeypatch.setattr(settings, 'distributed_runtime_enabled', True, raising=False)
        database.set_active_runtime_coordinator_generation(None)
        database.set_settings_engine_override(database._create_public_engine())
        asyncio.run(database.init_db())

        now = datetime.now(UTC)
        flight_specs = (
            ('active', enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING, None, None),
            ('cached', enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED, b'cached-response', now + timedelta(minutes=5)),
        )
        requests = [
            ComputeRequest(
                id=f'shared-flight-{suffix}',
                namespace='default',
                kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                status=status,
                command_envelope=b'{}',
                response_envelope=response,
                max_attempts=3,
                created_at=now,
                updated_at=now,
            )
            for suffix, status, response, _expires_at in flight_specs
        ]
        flights = [
            ComputeRequestFlight(
                namespace='default',
                flight_key=f'{suffix}-flight-key',
                request_id=f'shared-flight-{suffix}',
                created_at=now,
                expires_at=expires_at,
            )
            for suffix, _status, _response, expires_at in flight_specs
        ]
        request_ids = [request.id for request in requests]
        namespace_token = set_namespace_context('default')
        follower_session: Session | None = None
        try:
            with Session(database._get_tenant_engine()) as session:
                session.add_all([*requests, *flights])
                session.commit()

            follower_session = Session(database._get_tenant_engine())
            for suffix, _status, _response, _expires_at in flight_specs:
                reused = compute_requests_service._reusable_flight(
                    follower_session,
                    'default',
                    f'{suffix}-flight-key',
                    now=now,
                )
                assert reused is not None
                assert reused.id == f'shared-flight-{suffix}'

            completion_done = threading.Event()
            completion_errors: list[BaseException] = []

            def finalize_flights() -> None:
                token = set_namespace_context('default')
                try:
                    with Session(database._get_tenant_engine()) as session:
                        session.execute(text("SET LOCAL lock_timeout = '1500ms'"))
                        for request_id in request_ids:
                            request = session.get(ComputeRequest, request_id)
                            assert request is not None
                            compute_requests_service._finish_flight(session, request, cache_result=True, completed_at=now)
                        session.commit()
                except BaseException as exc:
                    completion_errors.append(exc)
                finally:
                    reset_namespace(token)
                    completion_done.set()

            completion_thread = threading.Thread(target=finalize_flights, name='shared-flight-finalizer')
            completion_thread.start()
            assert completion_done.wait(timeout=5), 'completion remained blocked behind active/cached flight followers'
            completion_thread.join(timeout=1)
            assert not completion_errors, completion_errors

            follower_session.close()
            follower_session = None

            datasource_id = 'shared-flight-race-datasource'
            command = command_from_payload(
                enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                {
                    'analysis_id': 'shared-flight-race-analysis',
                    'target_step_id': 'source',
                    'row_limit': 100,
                    'page': 1,
                    'analysis_pipeline': {
                        'analysis_id': 'shared-flight-race-analysis',
                        'tabs': [
                            {
                                'id': 'shared-flight-race-tab',
                                'datasource': {
                                    'id': datasource_id,
                                    'analysis_tab_id': 'shared-flight-race-tab',
                                    'source_type': 'file',
                                    'config': {'branch': 'main'},
                                },
                                'output': {'result_id': 'shared-flight-race-output', 'filename': 'result.csv', 'format': 'csv'},
                                'steps': [],
                            }
                        ],
                    },
                },
            )
            command_bytes = command.SerializeToString(deterministic=True)
            with Session(database._get_tenant_engine()) as session:
                session.add(
                    DataSource(
                        id=datasource_id,
                        name='Shared flight race source',
                        source_type='file',
                        config={'file_path': 's3://bucket/source.csv'},
                        created_at=now,
                    )
                )
                session.commit()

            concurrent_submitters = 20
            start_together = threading.Barrier(concurrent_submitters)

            def submit_identical_preview(_index: int) -> tuple[str, bool]:
                token = set_namespace_context('default')
                try:
                    start_together.wait(timeout=10)
                    deadline = time.monotonic() + 10
                    while True:
                        try:
                            with Session(database._get_tenant_engine()) as session:
                                request, created = compute_requests_service.stage_shared_flight_request(
                                    session,
                                    namespace='default',
                                    kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
                                    command=compute_pb2.ComputeCommand.FromString(command_bytes),
                                )
                                result = (request.id, created)
                                session.commit()
                                return result
                        except compute_requests_service.ComputeFlightLockBusy:
                            if time.monotonic() >= deadline:
                                raise TimeoutError('identical compute-flight submissions did not converge')
                            time.sleep(0.01)
                finally:
                    reset_namespace(token)

            with ThreadPoolExecutor(max_workers=concurrent_submitters, thread_name_prefix='flight-follower') as executor:
                staged_requests = list(executor.map(submit_identical_preview, range(concurrent_submitters)))

            durable_request_ids = {request_id for request_id, _created in staged_requests}
            assert len(durable_request_ids) == 1
            assert sum(created for _request_id, created in staged_requests) == 1
            durable_request_id = next(iter(durable_request_ids))
            with Session(database._get_tenant_engine()) as session:
                flight_count = len(
                    session.exec(
                        select(ComputeRequestFlight)
                        .where(ComputeRequestFlight.namespace == 'default')
                        .where(ComputeRequestFlight.request_id == durable_request_id)
                    ).all()
                )
            assert flight_count == 1
        finally:
            if follower_session is not None:
                follower_session.close()
            reset_namespace(namespace_token)
            _clear_database_state()


@pytest.mark.timeout(300)
def test_postgres_outbox_dispatchers_do_not_share_unclaimed_batch_rows(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from backend_core import database, runtime_outbox_service, runtime_work_service
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

        with Session(database._get_tenant_engine()) as session:
            assert runtime_work_service.list_pending_namespaces(session, kinds=[runtime_work_service.RuntimeWorkKind.OUTBOX]) == ['default']
            assert (
                session.execute(text("SELECT count(*) FROM public.runtime_namespace_work_wakes WHERE namespace = 'default' AND kind = 'outbox'")).scalar_one()
                == 2
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
                    'SELECT pending FROM public.runtime_namespace_work WHERE namespace = %s AND kind = %s',
                    ('default', 'outbox'),
                )
                is False
            )
        with Session(database._get_tenant_engine()) as session:
            assert runtime_work_service.list_pending_namespaces(session, kinds=[runtime_work_service.RuntimeWorkKind.OUTBOX]) == []
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

        recovered = asyncio.Event()

        async def recover() -> None:
            recovered.set()

        server = await runtime_ipc.start_api_server()
        assert server is not None
        engine = create_engine(container.url)
        try:
            task = asyncio.create_task(runtime_ipc.serve_api_notifications(server, stop_event, handler, recover=recover))
            await asyncio.wait_for(recovered.wait(), timeout=15)
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


@pytest.mark.timeout(480)
def test_postgres_runtime_coordinator_takeover_during_compute_terminal_publication(
    tmp_path: Path,
    rustfs_container: RustfsContainer,
    engine_runtime_env: dict[str, str],
) -> None:
    """A coordinator crash at the terminal row lock must recover without stale publication."""
    require_docker()

    with PostgresContainer() as container:
        data_dir = tmp_path / 'data'
        data_dir.mkdir(parents=True, exist_ok=True)
        api_port = free_port()
        coordinator_grpc_port = free_port()
        data_plane_port = free_port()
        base_env = _runtime_env(
            data_dir=data_dir,
            database_url=container.url,
            port=api_port,
            grpc_port=coordinator_grpc_port,
            rustfs=rustfs_container,
            data_plane_port=data_plane_port,
        )
        base_env.update(engine_runtime_env)
        # The test holds the request row while waiting up to 90 seconds for
        # terminal publication; renewal updates the same row and is blocked by
        # the test transaction, so preserve a 10-second lease margin.
        base_env['RUNTIME_WORK_LEASE_TTL_SECONDS'] = '120'
        _init_runtime_db(base_env)
        coordinator_application_name = f'dataforge-test-coordinator-{uuid.uuid4().hex[:12]}'

        api = ManagedProcess(
            name='publication-takeover-api',
            command=['uv', 'run', '--no-env-file', str(BACKEND_ROOT / 'main.py')],
            cwd=CORE_ROOT,
            env=base_env,
        )
        coordinator = _runtime_coordinator(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=coordinator_grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
            extra_env={
                'PGAPPNAME': coordinator_application_name,
                'RUNTIME_WORK_LEASE_TTL_SECONDS': '120',
            },
        )
        worker_manager = _worker_manager(
            data_dir=data_dir,
            database_url=container.url,
            grpc_port=coordinator_grpc_port,
            data_plane_port=data_plane_port,
            rustfs=rustfs_container,
            extra_env={**engine_runtime_env, 'RUNTIME_WORK_LEASE_TTL_SECONDS': '120'},
        )
        blocker_connection: psycopg.Connection | None = None
        preview_thread: threading.Thread | None = None
        preview_result: dict[str, object] = {}
        coordinator_processes_after_crash: list[str] = []
        terminated_coordinator_database_sessions: list[int] = []
        try:
            api.start()
            wait_for_http_ready(f'{_http_base_url(api_port)}/health/ready')
            coordinator.start()
            worker_manager.start()
            wait_for_condition(
                lambda: _registered_worker_count(container, 'coordinator') >= 1,
                timeout=90,
                description='coordinator registration before publication crash',
            )
            previous_generation = _coordinator_generation(container)
            assert previous_generation > 0

            import httpx

            with httpx.Client(base_url=_http_base_url(api_port), timeout=30) as client:
                datasource_id = _upload_datasource(client, 'coordinator-publication-takeover', content=_make_csv(200000))
                analysis = _create_analysis(client, 'Coordinator Publication Takeover', datasource_id, steps=_slow_steps())
                pipeline = analysis['pipeline_definition']
                assert isinstance(pipeline, dict)
                analysis_id = str(analysis['id'])
                tabs = pipeline.get('tabs')
                assert isinstance(tabs, list) and tabs
                first_tab = tabs[0]
                assert isinstance(first_tab, dict)
                steps = first_tab.get('steps')
                assert isinstance(steps, list) and steps
                preview_request = {
                    'analysis_id': analysis_id,
                    'target_step_id': str(steps[-1]['id']),
                    'analysis_pipeline': {'analysis_id': analysis_id, **pipeline},
                    'row_limit': 50,
                    'page': 1,
                }

            def submit_preview() -> None:
                try:
                    with httpx.Client(base_url=_http_base_url(api_port), timeout=300) as preview_client:
                        preview_result['response'] = preview_client.post('/api/v1/compute/preview', json=preview_request)
                except BaseException as exc:
                    preview_result['error'] = exc

            preview_thread = threading.Thread(target=submit_preview, name='coordinator-publication-preview')
            preview_thread.start()

            def running_preview_request() -> tuple[str, int] | None:
                request = _active_preview_request_with_lease(container)
                if request is None or request[1] != enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING or request[2] < 100:
                    return None
                return request[0], request[1]

            active = wait_for_condition(
                running_preview_request,
                timeout=90,
                interval=0.1,
                description='durable preview request to receive its renewed work lease',
            )
            request_id, active_status = active
            assert active_status == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING

            blocker_connection = psycopg.connect(container.url.replace('+psycopg', ''))
            blocker_pid_row = blocker_connection.execute('SELECT pg_backend_pid()').fetchone()
            assert blocker_pid_row is not None
            blocker_pid = int(blocker_pid_row[0])
            claim_row = blocker_connection.execute(
                'SELECT status, lease_owner, claim_token, lease_generation FROM "default".compute_requests WHERE id = %s FOR UPDATE',
                (request_id,),
            ).fetchone()
            assert claim_row is not None and int(claim_row[0]) == enums_pb2.COMPUTE_REQUEST_STATUS_RUNNING
            worker_id, claim_token, lease_generation = str(claim_row[1]), str(claim_row[2]), int(claim_row[3])
            assert worker_id and claim_token and lease_generation > 0

            try:
                blocked = wait_for_condition(
                    lambda: _blocked_compute_terminal_publications(container, blocker_pid),
                    timeout=90,
                    interval=0.1,
                    description='coordinator terminal publication SELECT FOR UPDATE to wait on the held compute row',
                )
            except AssertionError as exc:
                lock_activity = _runtime_coordinator_lock_activity(container)
                raise AssertionError(f'{exc}; database lock activity={lock_activity!r}') from exc
            assert blocked is not None
            assert len(blocked) == 1, f'expected one blocked terminal publication, found {blocked!r}'
            assert 'FOR UPDATE' in blocked[0][1].upper()

            worker_registration_count = _worker_registration_count(container, 'coordinator')
            coordinator.crash()
            coordinator_processes_after_crash = _runtime_coordinator_processes()
            assert not coordinator_processes_after_crash, f'coordinator processes survived SIGKILL: {coordinator_processes_after_crash!r}'
            # Test services reach the nested-Docker Postgres through its
            # published-port proxy. After proving the owner process is gone,
            # close only its tagged backend sessions: the proxy can retain
            # those sockets longer than a direct production DB connection.
            terminated_coordinator_database_sessions = _terminate_coordinator_database_sessions(container, coordinator_application_name)
            wait_for_condition(
                lambda: not _coordinator_database_sessions(container, coordinator_application_name),
                timeout=10,
                interval=0.1,
                description='terminated coordinator database sessions to close',
            )
            coordinator.start()
            try:
                wait_for_condition(
                    lambda: _coordinator_generation(container) > previous_generation,
                    timeout=90,
                    description='new fenced coordinator generation during terminal publication',
                )
            except AssertionError as exc:
                lock_activity = _runtime_coordinator_lock_activity(container)
                postgres_clients = _coordinator_database_sessions(container, coordinator_application_name)
                replacement_pid = coordinator.proc.pid if coordinator.proc is not None else None
                raise AssertionError(
                    f'{exc}; database lock activity={lock_activity!r}; active coordinator sessions={postgres_clients!r}; '
                    f'terminated coordinator sessions={terminated_coordinator_database_sessions!r}; '
                    f'coordinator processes after crash={coordinator_processes_after_crash!r}; replacement_pid={replacement_pid}'
                ) from exc
            wait_for_condition(
                lambda: _worker_registration_count(container, 'coordinator') > worker_registration_count,
                timeout=90,
                description='worker manager resynchronization after publication-time coordinator crash',
            )

            # The killed coordinator's blocked transaction must have rolled
            # back. Releasing the test lock lets normal lease expiry and
            # durable request recovery proceed under the replacement owner.
            blocker_connection.rollback()
            blocker_connection.close()
            blocker_connection = None

            def completed_request() -> tuple[object, ...] | None:
                with container.connect() as connection:
                    row = connection.execute(
                        'SELECT status, response_envelope, completed_at, attempts, lease_owner, claim_token FROM "default".compute_requests WHERE id = %s',
                        (request_id,),
                    ).fetchone()
                if row is None or int(row[0]) != enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED:
                    return None
                return tuple(row)

            terminal = wait_for_condition(
                completed_request,
                timeout=240,
                interval=0.5,
                description='durable preview completion after coordinator takeover',
            )
            assert terminal[1] is not None and terminal[2] is not None
            assert terminal[4] is None and terminal[5] is None
            preview_thread.join(timeout=30)
            assert not preview_thread.is_alive(), 'preview waiter did not observe the recovered durable result'
            preview_response = preview_result.get('response')
            assert isinstance(preview_response, httpx.Response), f'preview waiter failed: {preview_result!r}'
            assert preview_response.status_code == 200, preview_response.text
            assert preview_response.json().get('data')

            with container.connect() as connection:
                request_count = _query_value(connection, 'SELECT count(*) FROM "default".compute_requests WHERE id = %s', (request_id,))
                flight_count = _query_value(connection, 'SELECT count(*) FROM "default".compute_request_flights WHERE request_id = %s', (request_id,))
                run_count = _query_value(
                    connection,
                    'SELECT count(*) FROM "default".compute_worker_runs WHERE analysis_id = %s AND kind = %s',
                    (analysis_id, 'preview'),
                )
                accepted_snapshot = connection.execute(
                    'SELECT status, response_envelope, completed_at, attempts FROM "default".compute_requests WHERE id = %s',
                    (request_id,),
                ).fetchone()
            assert request_count == 1
            assert flight_count == 1
            assert run_count == 1

            # Exercise the actual replacement coordinator interceptor with an
            # otherwise-valid terminal RPC carrying the old owner generation.
            import grpc

            from dataforge_protocol import worker_runtime_pb2, worker_runtime_pb2_grpc

            stale_completion = worker_runtime_pb2.WorkerCompleteComputeRequestRequest(
                namespace='default',
                request_id=request_id,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_generation=lease_generation,
                response_envelope=compute_pb2.ComputeResponseEnvelope.FromString(bytes(terminal[1])),
            )
            with grpc.insecure_channel(f'{process_host()}:{coordinator_grpc_port}') as channel:
                grpc.channel_ready_future(channel).result(timeout=30)
                stub = worker_runtime_pb2_grpc.WorkerRuntimeServiceStub(channel)
                with pytest.raises(grpc.RpcError) as stale_call:
                    stub.CompleteComputeRequest(
                        stale_completion,
                        timeout=15,
                        metadata=(
                            ('x-internal-token', INTERNAL_API_TOKEN),
                            ('x-runtime-coordinator-generation', str(previous_generation)),
                        ),
                    )
            assert stale_call.value.code() == grpc.StatusCode.FAILED_PRECONDITION
            with container.connect() as connection:
                after_stale_call = connection.execute(
                    'SELECT status, response_envelope, completed_at, attempts FROM "default".compute_requests WHERE id = %s',
                    (request_id,),
                ).fetchone()
            assert after_stale_call == accepted_snapshot, 'stale generation changed the accepted terminal result'
        except AssertionError as exc:
            raise AssertionError(
                f'{exc}\napi tail:\n{api.tail()}\ncoordinator tail:\n{coordinator.tail()}\n'
                f'worker manager tail:\n{worker_manager.tail()}\npreview outcome: {preview_result!r}'
            ) from exc
        finally:
            if blocker_connection is not None:
                blocker_connection.rollback()
                blocker_connection.close()
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
                try:
                    datasource_id = _upload_datasource(client_one, 'cross-api-runtime', content=_make_csv(200000))
                except AssertionError as exc:
                    raise AssertionError(
                        f'{exc}'
                        + _runtime_failure_context(
                            container,
                            api_one=api_one,
                            api_two=api_two,
                            coordinator=coordinator,
                            worker_manager=worker_manager,
                        )
                    ) from exc
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
                        'SELECT count(*) FROM "default".compute_worker_runs WHERE kind = %s',
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
                try:
                    datasource_id = _upload_datasource(client_one, 'cross-api-cancel', content=big_csv)
                except AssertionError as exc:
                    raise AssertionError(
                        f'{exc}'
                        + _runtime_failure_context(
                            container,
                            api_one=api_one,
                            api_two=api_two,
                            coordinator=coordinator,
                            worker_manager=worker_manager,
                        )
                    ) from exc
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
