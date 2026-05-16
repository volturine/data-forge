from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from harness.postgres_harness import (
    BACKEND_ROOT,
    CORE_ROOT,
    WORKER_ROOT,
    ManagedProcess,
    PostgresContainer,
    docker_env,
    free_port,
    require_docker,
    run_command,
    wait_for_condition,
    wait_for_http_ready,
)
from sqlalchemy import text
from sqlmodel import Session
from websockets.asyncio.client import connect


def _clear_database_state() -> None:
    from core import database

    if database.settings_engine is not None:
        database.settings_engine.dispose()
        database.settings_engine = None
    if database.tenant_engine is not None:
        database.tenant_engine.dispose()
        database.tenant_engine = None
    database.clear_namespace_init_cache()
    database.clear_engine_override()
    database.clear_settings_engine_override()


def _table_exists(connection: psycopg.Connection, schema: str, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchone()
    return row is not None


def _query_value(connection: psycopg.Connection, sql: str, params: tuple[object, ...] = ()):
    row = connection.execute(sql, params).fetchone()
    return row[0] if row is not None else None


SAMPLE_CSV = "id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n"


def _make_csv(rows: int) -> str:
    header = "id,name,age,city,score\n"
    body = "".join(f"{index},name-{index},{20 + (index % 50)},city-{index % 100},{index % 1000}\n" for index in range(1, rows + 1))
    return header + body


def _runtime_env(*, data_dir: Path, database_url: str, port: int) -> dict[str, str]:
    return docker_env(
        {
            "ENV_FILE": "",
            "APP_NAME": "Data-Forge Runtime Test",
            "APP_VERSION": "0.0.0-test",
            "DEBUG": "false",
            "PROD_MODE_ENABLED": "false",
            "PORT": str(port),
            "DATA_DIR": str(data_dir),
            "DATABASE_URL": database_url,
            "DISTRIBUTED_RUNTIME_ENABLED": "true",
            "DEFAULT_NAMESPACE": "default",
            "AUTH_REQUIRED": "false",
            "LOG_LEVEL": "warning",
            "UVICORN_ACCESS_LOG": "false",
            "WORKERS": "1",
            "WORKER_CONNECTIONS": "100",
            "CORS_ORIGINS": f"http://127.0.0.1:{port}",
            "AUTH_FRONTEND_URL": f"http://127.0.0.1:{port}",
        }
    )


def _init_runtime_db(env: dict[str, str]) -> None:
    run_command(
        [
            "uv",
            "run",
            "python",
            "-c",
            "import asyncio; from core.database import init_db; asyncio.run(init_db())",
        ],
        cwd=CORE_ROOT,
        env=env,
        timeout=300,
    )


def _upload_datasource(client, name: str, *, content: str = SAMPLE_CSV) -> str:
    response = client.post(
        "/api/v1/datasource/upload",
        files={"file": (f"{name}.csv", content.encode("utf-8"), "text/csv")},
        data={"name": name},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


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
            "id": str(uuid.uuid4()),
            "type": "view",
            "config": {},
            "depends_on": [],
            "is_applied": True,
        }
    ]
    response = client.post(
        "/api/v1/analysis",
        json={
            "name": name,
            "description": None,
            "tabs": [
                {
                    "id": tab_id,
                    "name": "Source 1",
                    "parent_id": None,
                    "datasource": {
                        "id": datasource_id,
                        "analysis_tab_id": None,
                        "config": {"branch": "master"},
                    },
                    "output": {
                        "result_id": result_id,
                        "datasource_type": "iceberg",
                        "format": "parquet",
                        "filename": "source_1",
                        "build_mode": "full",
                        "iceberg": {
                            "namespace": "outputs",
                            "table_name": "source_1",
                            "branch": "master",
                        },
                    },
                    "steps": tab_steps,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _start_build(client, analysis: dict[str, object]) -> str:
    pipeline = analysis["pipeline_definition"]
    assert isinstance(pipeline, dict)
    analysis_id = analysis["id"]
    assert isinstance(analysis_id, str)
    tabs = pipeline.get("tabs")
    assert isinstance(tabs, list) and tabs
    first_tab = tabs[0]
    assert isinstance(first_tab, dict)
    tab_id = first_tab.get("id")
    assert isinstance(tab_id, str)
    response = client.post(
        "/api/v1/compute/builds/active",
        json={
            "analysis_pipeline": {
                "analysis_id": analysis_id,
                **pipeline,
            },
            "tab_id": tab_id,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["build_id"])


def _wait_for_running_build(client, build_id: str, *, timeout: float = 180) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/compute/builds/active/{build_id}")
        if response.status_code == 200:
            detail = dict(response.json())
            if detail.get("status") == "running":
                return detail
            if detail.get("status") in {"completed", "failed", "cancelled"}:
                raise AssertionError(f"Build {build_id} reached terminal state before cancellation: {detail}")
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for build {build_id} to start running")


def _slow_steps() -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    prev: str | None = None
    for index in range(40):
        step_id = str(uuid.uuid4())
        step = {
            "id": step_id,
            "type": "filter",
            "config": {
                "conditions": [
                    {
                        "column": "score",
                        "operator": ">",
                        "value": index,
                        "value_type": "number",
                    }
                ],
                "logic": "AND",
            },
            "depends_on": [prev] if prev is not None else [],
            "is_applied": True,
        }
        steps.append(step)
        prev = step_id
    return steps


@pytest.mark.timeout(300)
def test_init_db_bootstraps_public_and_tenant_schemas_in_postgres(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from core import database
    from core.config import settings
    from core.namespace import namespace_paths

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
        monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        namespace_paths("default")
        namespace_paths("alpha")

        asyncio.run(database.init_db())

        with container.connect() as connection:
            assert _table_exists(connection, "public", "app_settings")
            assert not _table_exists(connection, "public", "users")
            assert _table_exists(connection, "public", "runtime_workers")
            assert _table_exists(connection, "public", "engine_instances")
            assert _table_exists(connection, "default", "build_runs")
            assert _table_exists(connection, "default", "build_jobs")
            assert _table_exists(connection, "alpha", "build_runs")
            assert _table_exists(connection, "alpha", "build_jobs")
            assert _query_value(connection, "SELECT count(*) FROM public.app_settings") == 1
            assert _query_value(connection, "SELECT version_num FROM public.alembic_version") == "0001_runtime_public"
            assert _query_value(connection, 'SELECT version_num FROM "default".alembic_version') == "0002_runtime_tenant"
            assert _query_value(connection, "SELECT version_num FROM alpha.alembic_version") == "0002_runtime_tenant"

        _clear_database_state()


@pytest.mark.timeout(300)
def test_init_db_postgres_shared_seed_is_safe_under_concurrent_startup(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from core import database
    from core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
        monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
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
            assert _query_value(connection, "SELECT count(*) FROM public.app_settings") == 1
            assert not _table_exists(connection, "public", "users")

        _clear_database_state()


@pytest.mark.timeout(300)
def test_backend_public_bootstrap_creates_auth_tables_and_default_user(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from core import database
    from core.config import settings

    from backend_core.auth_config import settings as auth_settings
    from backend_core.public_schema import ensure_backend_public_tables
    from modules.auth.service import ensure_default_user

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
        monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
        monkeypatch.setattr(auth_settings, "default_user_email", "seeded@example.com", raising=False)
        monkeypatch.setattr(auth_settings, "default_user_password", "SeededPass123", raising=False)
        monkeypatch.setattr(auth_settings, "default_user_name", "Seeded User", raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())
        ensure_backend_public_tables()
        database.run_settings_db(ensure_default_user)

        with container.connect() as connection:
            assert _table_exists(connection, "public", "users")
            assert _table_exists(connection, "public", "auth_providers")
            assert _table_exists(connection, "public", "user_sessions")
            assert _table_exists(connection, "public", "verification_tokens")
            assert _table_exists(connection, "public", "chat_sessions")
            assert _query_value(connection, "SELECT count(*) FROM public.users") == 1

        _clear_database_state()


@pytest.mark.timeout(300)
def test_init_db_postgres_namespace_bootstrap_does_not_deadlock(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from core import database
    from core.config import settings
    from core.namespace import namespace_paths

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
        monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())
        namespace_paths("default")

        thread = threading.Thread(target=lambda: asyncio.run(database.init_db()))
        thread.start()
        thread.join(timeout=30)

        assert not thread.is_alive()

        with container.connect() as connection:
            assert _table_exists(connection, "default", "build_runs")

        _clear_database_state()


@pytest.mark.timeout(300)
def test_namespace_connection_sets_search_path(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from core import database
    from core.config import settings

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
        monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())

        with database.namespace_connection("default") as connection:
            assert connection.execute(text("SELECT current_schema()")).scalar_one() == "default"

        _clear_database_state()


@pytest.mark.timeout(300)
def test_tenant_engine_checkout_tracks_current_namespace(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from core import database
    from core.config import settings
    from core.namespace import reset_namespace, set_namespace_context

    with PostgresContainer() as container:
        _clear_database_state()
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", data_dir, raising=False)
        monkeypatch.setattr(settings, "distributed_runtime_enabled", True, raising=False)
        database.set_settings_engine_override(database._create_public_engine())

        asyncio.run(database.init_db())
        database._init_namespace_db("alpha")
        database._init_namespace_db("beta")

        alpha_token = set_namespace_context("alpha")
        try:
            with Session(database._get_tenant_engine()) as alpha_session:
                assert alpha_session.connection().execute(text("SELECT current_schema()")).scalar_one() == "alpha"
        finally:
            reset_namespace(alpha_token)

        beta_token = set_namespace_context("beta")
        try:
            with Session(database._get_tenant_engine()) as beta_session:
                assert beta_session.connection().execute(text("SELECT current_schema()")).scalar_one() == "beta"
        finally:
            reset_namespace(beta_token)

        _clear_database_state()


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_postgres_runtime_ipc_delivers_notifications(monkeypatch, tmp_path: Path) -> None:
    require_docker()

    from contracts.runtime import ipc as runtime_ipc
    from contracts.runtime.ipc import RuntimePayloadKind
    from core.config import settings

    with PostgresContainer() as container:
        monkeypatch.setattr(settings, "database_url", container.url, raising=False)
        monkeypatch.setattr(settings, "data_dir", tmp_path / "data", raising=False)

        received: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        stop_event = asyncio.Event()

        async def handler(payload: dict[str, object]) -> None:
            await received.put(payload)

        server = await runtime_ipc.start_api_server()
        assert server is not None
        try:
            task = asyncio.create_task(runtime_ipc.serve_api_notifications(server, stop_event, handler))
            await asyncio.to_thread(runtime_ipc.notify_api_build, "default", "build-1", 7)
            await asyncio.to_thread(runtime_ipc.notify_build_job)

            build_payload = await asyncio.wait_for(received.get(), timeout=15)
            job_payload = await asyncio.wait_for(received.get(), timeout=15)

            assert build_payload == {
                "kind": RuntimePayloadKind.BUILD.value,
                "namespace": "default",
                "build_id": "build-1",
                "latest_sequence": 7,
            }
            assert job_payload == {"kind": RuntimePayloadKind.JOB.value}
        finally:
            stop_event.set()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(task, timeout=5)
            await runtime_ipc.stop_api_server(server)


@pytest.mark.asyncio
@pytest.mark.timeout(300)
async def test_postgres_runtime_supports_cross_api_build_detail_and_replay(
    tmp_path: Path,
) -> None:
    require_docker()

    with PostgresContainer() as container:
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        api_one_port = free_port()
        api_two_port = free_port()

        base_env = _runtime_env(data_dir=data_dir, database_url=container.url, port=api_one_port)
        _init_runtime_db(base_env)

        api_one = ManagedProcess(
            name="api-one",
            command=["uv", "run", "--no-env-file", str(BACKEND_ROOT / "main.py")],
            cwd=CORE_ROOT,
            env=_runtime_env(data_dir=data_dir, database_url=container.url, port=api_one_port),
        )
        api_two = ManagedProcess(
            name="api-two",
            command=["uv", "run", "--no-env-file", str(BACKEND_ROOT / "main.py")],
            cwd=CORE_ROOT,
            env=_runtime_env(data_dir=data_dir, database_url=container.url, port=api_two_port),
        )
        worker = ManagedProcess(
            name="worker",
            command=["uv", "run", "--no-env-file", str(WORKER_ROOT / "main.py")],
            cwd=CORE_ROOT,
            env=_runtime_env(data_dir=data_dir, database_url=container.url, port=api_one_port),
        )
        try:
            api_one.start()
            api_two.start()
            worker.start()

            try:
                wait_for_http_ready(f"http://127.0.0.1:{api_one_port}/health/ready")
                wait_for_http_ready(f"http://127.0.0.1:{api_two_port}/health/ready")
            except AssertionError as exc:
                raise AssertionError(f"{exc}\napi-one tail:\n{api_one.tail()}\napi-two tail:\n{api_two.tail()}\nworker tail:\n{worker.tail()}") from exc

            def _api_worker_count() -> int:
                with container.connect() as connection:
                    value = _query_value(
                        connection,
                        "SELECT count(*) FROM public.runtime_workers WHERE kind = 'api' AND stopped_at IS NULL",
                    )
                return int(value) if value is not None else 0

            wait_for_condition(
                lambda: _api_worker_count() >= 2,
                timeout=90,
                description="two api workers to register",
            )

            import httpx

            with httpx.Client(base_url=f"http://127.0.0.1:{api_one_port}", timeout=30) as client_one:
                datasource_id = _upload_datasource(client_one, "cross-api-runtime")
                analysis = _create_analysis(client_one, "Cross API Runtime", datasource_id)
                build_id = _start_build(client_one, analysis)

            with httpx.Client(base_url=f"http://127.0.0.1:{api_two_port}", timeout=30) as client_two:
                detail = wait_for_condition(
                    lambda: (
                        response.json()
                        if (response := client_two.get(f"/api/v1/compute/builds/active/{build_id}")).status_code == 200
                        and response.json().get("status") in {"completed", "failed", "cancelled"}
                        else None
                    ),
                    timeout=180,
                    interval=1,
                    description="build detail from second api worker",
                )

                assert detail["build_id"] == build_id
                assert detail["status"] == "completed"

            async with connect(f"ws://127.0.0.1:{api_two_port}/api/v1/compute/ws/builds/{build_id}?namespace=default") as websocket:
                snapshot = json.loads(await websocket.recv())

            assert snapshot["type"] == "snapshot"
            assert snapshot["build"]["build_id"] == build_id
            assert snapshot["build"]["status"] == "completed"
            assert isinstance(snapshot["last_sequence"], int)
            assert snapshot["last_sequence"] >= 1

            if snapshot["last_sequence"] > 1:
                async with connect(f"ws://127.0.0.1:{api_two_port}/api/v1/compute/ws/builds/{build_id}?namespace=default&last_sequence=1") as websocket:
                    replay = json.loads(await websocket.recv())

                assert replay["build_id"] == build_id
                assert replay["sequence"] > 1
        finally:
            worker.stop()
            api_two.stop()
            api_one.stop()


@pytest.mark.timeout(300)
def test_postgres_runtime_supports_cross_api_cancellation(tmp_path: Path) -> None:
    require_docker()

    with PostgresContainer() as container:
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        api_one_port = free_port()
        api_two_port = free_port()

        base_env = _runtime_env(data_dir=data_dir, database_url=container.url, port=api_one_port)
        _init_runtime_db(base_env)

        api_one = ManagedProcess(
            name="api-one",
            command=["uv", "run", "--no-env-file", str(BACKEND_ROOT / "main.py")],
            cwd=CORE_ROOT,
            env=_runtime_env(data_dir=data_dir, database_url=container.url, port=api_one_port),
        )
        api_two = ManagedProcess(
            name="api-two",
            command=["uv", "run", "--no-env-file", str(BACKEND_ROOT / "main.py")],
            cwd=CORE_ROOT,
            env=_runtime_env(data_dir=data_dir, database_url=container.url, port=api_two_port),
        )
        worker = ManagedProcess(
            name="worker",
            command=["uv", "run", "--no-env-file", str(WORKER_ROOT / "main.py")],
            cwd=CORE_ROOT,
            env=_runtime_env(data_dir=data_dir, database_url=container.url, port=api_one_port),
        )
        try:
            api_one.start()
            api_two.start()
            worker.start()

            try:
                wait_for_http_ready(f"http://127.0.0.1:{api_one_port}/health/ready")
                wait_for_http_ready(f"http://127.0.0.1:{api_two_port}/health/ready")
            except AssertionError as exc:
                raise AssertionError(f"{exc}\napi-one tail:\n{api_one.tail()}\napi-two tail:\n{api_two.tail()}\nworker tail:\n{worker.tail()}") from exc

            def _api_worker_count() -> int:
                with container.connect() as connection:
                    value = _query_value(
                        connection,
                        "SELECT count(*) FROM public.runtime_workers WHERE kind = 'api' AND stopped_at IS NULL",
                    )
                return int(value) if value is not None else 0

            wait_for_condition(
                lambda: _api_worker_count() >= 2,
                timeout=90,
                description="two api workers to register",
            )

            import httpx

            big_csv = _make_csv(200000)

            with httpx.Client(base_url=f"http://127.0.0.1:{api_one_port}", timeout=30) as client_one:
                datasource_id = _upload_datasource(client_one, "cross-api-cancel", content=big_csv)
                analysis = _create_analysis(client_one, "Cross API Cancel", datasource_id, steps=_slow_steps())
                build_id = _start_build(client_one, analysis)
                _wait_for_running_build(client_one, build_id, timeout=180)

            with httpx.Client(base_url=f"http://127.0.0.1:{api_two_port}", timeout=30) as client_two:
                cancelled = client_two.post(f"/api/v1/compute/builds/active/{build_id}/cancel")

                assert cancelled.status_code == 200, cancelled.text
                payload = dict(cancelled.json())
                assert payload["build_id"] == build_id
                assert payload["engine_run_id"] is None
                assert payload["status"] == "cancelled"

                detail = wait_for_condition(
                    lambda: (
                        response.json()
                        if (response := client_two.get(f"/api/v1/compute/builds/active/{build_id}")).status_code == 200
                        and response.json().get("status") == "cancelled"
                        else None
                    ),
                    timeout=180,
                    interval=1,
                    description="cancelled build detail from second api worker",
                )

                assert detail["build_id"] == build_id
                assert detail["current_engine_run_id"] is None
                assert detail["status"] == "cancelled"
                assert detail["cancelled_by"]

            with container.connect() as connection:
                build_status = _query_value(
                    connection,
                    'SELECT status FROM "default".build_runs WHERE id = %s',
                    (build_id,),
                )

            assert build_status == "cancelled"
        finally:
            worker.stop()
            api_two.stop()
            api_one.stop()
