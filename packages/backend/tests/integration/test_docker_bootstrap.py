from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest

SAMPLE_CSV = "id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n"


def _base_url() -> str:
    value = os.environ.get("RUNTIME_TEST_BASE_URL")
    if value:
        return value
    pytest.skip("Docker runtime bootstrap tests require RUNTIME_TEST_BASE_URL")


def _db_url() -> str:
    value = os.environ.get("RUNTIME_TEST_DB_URL")
    if value:
        return value
    pytest.skip("Docker runtime bootstrap tests require RUNTIME_TEST_DB_URL")


def _default_user_email() -> str:
    value = os.environ.get("DEFAULT_USER_EMAIL")
    if value:
        return value
    pytest.skip("Docker runtime bootstrap tests require DEFAULT_USER_EMAIL")


def _default_user_password() -> str:
    value = os.environ.get("DEFAULT_USER_PASSWORD")
    if value:
        return value
    pytest.skip("Docker runtime bootstrap tests require DEFAULT_USER_PASSWORD")


def _psql_value(sql: str) -> str:
    with psycopg.connect(_db_url(), autocommit=True) as connection:
        row = connection.execute(sql).fetchone()
    if row is None:
        return ""
    return str(row[0])


def _wait_for_build_detail(client: httpx.Client, build_id: str, *, timeout: float = 180) -> dict[str, object]:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout)
    while datetime.now(UTC) < deadline:
        response = client.get(f"/api/v1/compute/builds/active/{build_id}")
        if response.status_code == 200:
            detail = dict(response.json())
            if detail.get("status") in {"completed", "failed", "cancelled"}:
                return detail
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))
    raise AssertionError(f"Timed out waiting for build {build_id} to reach a terminal state")


def _wait_for_runtime_workers() -> tuple[int, int]:
    deadline = time.time() + 120
    while time.time() < deadline:
        worker_count = int(_psql_value("SELECT count(*) FROM public.runtime_workers WHERE kind = 'build_manager' AND stopped_at IS NULL"))
        scheduler_count = int(_psql_value("SELECT count(*) FROM public.runtime_workers WHERE kind = 'scheduler' AND stopped_at IS NULL"))
        if worker_count >= 1 and scheduler_count >= 1:
            return worker_count, scheduler_count
        time.sleep(1)
    raise AssertionError("Timed out waiting for runtime worker and scheduler registration")


def _api_worker_count() -> int:
    value = os.environ.get("WORKERS")
    if value is None:
        return 1
    return max(1, int(value))


def _wait_for_api_workers(min_count: int) -> int:
    deadline = time.time() + 120
    while time.time() < deadline:
        count = int(_psql_value("SELECT count(*) FROM public.runtime_workers WHERE kind = 'api' AND stopped_at IS NULL"))
        if count >= min_count:
            return count
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for {min_count} api workers to register")


def _wait_for_scheduled_build(schedule_id: str) -> tuple[str, str]:
    deadline = time.time() + 240
    failure = ""
    while time.time() < deadline:
        failure = _psql_value(
            f"SELECT COALESCE(last_failure_at::text, '') FROM \"default\".schedules WHERE id = '{schedule_id}' AND last_failure_at IS NOT NULL"
        )
        if failure:
            raise AssertionError(f"Scheduled build enqueue failed for {schedule_id} at {failure}")
        row = _psql_value(f"SELECT concat(id, '|', status) FROM \"default\".build_runs WHERE schedule_id = '{schedule_id}' ORDER BY created_at DESC LIMIT 1")
        if row and "|" in row:
            build_id, status = row.split("|", maxsplit=1)
            if status in {"completed", "failed", "cancelled", "orphaned"}:
                return build_id, status
        time.sleep(1)
    schedule_state = _psql_value(
        f"SELECT concat(enabled, '|', COALESCE(next_run::text, ''), '|', COALESCE(lease_owner, '')) FROM \"default\".schedules WHERE id = '{schedule_id}'"
    )
    build_state = _psql_value(
        "SELECT concat(id, '|', status, '|', COALESCE(error_message, '')) "
        'FROM "default".build_runs '
        f"WHERE schedule_id = '{schedule_id}' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    job_state = ""
    if build_state and "|" in build_state:
        build_id = build_state.split("|", maxsplit=1)[0]
        job_state = _psql_value(
            "SELECT concat(id, '|', status, '|', COALESCE(lease_owner, ''), '|', COALESCE(last_error, '')) "
            'FROM "default".build_jobs '
            f"WHERE build_id = '{build_id}' "
            "ORDER BY created_at DESC LIMIT 1"
        )
    worker_state = _psql_value(
        "SELECT string_agg(concat(kind, ':', id, ':', active_jobs, ':', COALESCE(stopped_at::text, '')), ',') "
        "FROM public.runtime_workers "
        "WHERE kind IN ('build_manager', 'build_worker')"
    )
    raise AssertionError(
        f"Timed out waiting for scheduled build for {schedule_id}; schedule={schedule_state}; "
        f"build={build_state}; job={job_state}; workers={worker_state}; failure={failure}"
    )


def _upload_datasource(client: httpx.Client, name: str) -> str:
    response = client.post(
        "/api/v1/datasource/upload",
        files={"file": (f"{name}.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        data={"name": name},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _login_default_user(client: httpx.Client) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": _default_user_email(),
            "password": _default_user_password(),
        },
    )
    assert response.status_code == 200, response.text
    token = response.cookies.get("session_token")
    assert token
    client.headers["X-Session-Token"] = token


def _create_analysis(client: httpx.Client, name: str, datasource_id: str) -> dict[str, object]:
    result_id = str(uuid.uuid4())
    tab_id = str(uuid.uuid4())
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
                    "steps": [
                        {
                            "id": str(uuid.uuid4()),
                            "type": "view",
                            "config": {},
                            "depends_on": [],
                            "is_applied": True,
                        }
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def _start_build(client: httpx.Client, analysis: dict[str, object]) -> str:
    pipeline = analysis["pipeline_definition"]
    assert isinstance(pipeline, dict)
    analysis_id = analysis["id"]
    assert isinstance(analysis_id, str) and analysis_id
    tabs = pipeline["tabs"]
    assert isinstance(tabs, list) and tabs
    first_tab = tabs[0]
    assert isinstance(first_tab, dict)
    response = client.post(
        "/api/v1/compute/builds/active",
        json={
            "analysis_pipeline": {
                "analysis_id": analysis_id,
                **pipeline,
            },
            "tab_id": first_tab["id"],
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["build_id"])


def test_postgres_runtime_bootstraps_public_and_tenant_schemas() -> None:
    assert _psql_value("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'default' AND table_name = 'build_runs'") == "1"
    assert _psql_value("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'runtime_workers'") == "1"
    assert _psql_value("SELECT count(*) FROM public.app_settings") == "1"
    assert _psql_value("SELECT count(*) FROM public.users") == "1"
    assert _psql_value("SELECT version_num FROM public.alembic_version") == "0001_runtime_public"
    assert _psql_value('SELECT version_num FROM "default".alembic_version') == "0002_runtime_tenant"


@pytest.mark.timeout(300)
def test_postgres_runtime_coordinates_api_worker_and_scheduler() -> None:
    _wait_for_runtime_workers()
    expected_api_workers = _api_worker_count()
    api_workers = _wait_for_api_workers(expected_api_workers)
    assert api_workers >= expected_api_workers

    with httpx.Client(base_url=_base_url(), timeout=30) as client:
        _login_default_user(client)
        datasource_id = _upload_datasource(client, "docker-runtime-ds")
        analysis = _create_analysis(client, "Docker Runtime Analysis", datasource_id)
        build_id = _start_build(client, analysis)
        detail = _wait_for_build_detail(client, build_id)

        assert detail["status"] == "completed"

        pipeline = analysis["pipeline_definition"]
        assert isinstance(pipeline, dict)
        tabs = pipeline["tabs"]
        assert isinstance(tabs, list) and tabs
        first_tab = tabs[0]
        assert isinstance(first_tab, dict)
        output = first_tab["output"]
        assert isinstance(output, dict)
        output_id = str(output["result_id"])

        schedule = client.post(
            "/api/v1/schedules",
            json={
                "datasource_id": output_id,
                "cron_expression": "0 0 1 1 *",
                "enabled": True,
            },
        )
        assert schedule.status_code == 200, schedule.text
        schedule_id = str(schedule.json()["id"])

    run_at = (datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None).isoformat(sep=" ")
    with psycopg.connect(_db_url(), autocommit=True) as connection:
        connection.execute(
            'UPDATE "default".schedules SET next_run = %s WHERE id = %s',
            (run_at, schedule_id),
        )

    scheduled_build_id, scheduled_status = _wait_for_scheduled_build(schedule_id)

    assert scheduled_status == "completed"
    assert scheduled_build_id != build_id
