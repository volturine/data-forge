"""Verify a freshly started E2E stack: schema bootstrap, a manual build, and a scheduler-fired build."""

from __future__ import annotations

import argparse
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

_SAMPLE_CSV = 'id,name,age,city\n1,Alice,30,London\n2,Bob,25,Paris\n3,Charlie,35,Berlin\n'
_TERMINAL_BUILD_STATUSES = {'completed', 'failed', 'cancelled', 'orphaned'}


def _scalar(db_url: str, sql: str, params: tuple[object, ...] = ()) -> str:
    with psycopg.connect(db_url, autocommit=True) as connection:
        row = connection.execute(sql, params).fetchone()
    return '' if row is None or row[0] is None else str(row[0])


def check_schema_bootstrap(db_url: str, expected_revision: str) -> None:
    checks = {
        'default.build_runs exists': "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'default' AND table_name = 'build_runs'",
        'public.runtime_workers exists': "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'runtime_workers'",
        'one app_settings row': 'SELECT count(*) FROM public.app_settings',
        'only the default user': 'SELECT count(*) FROM public.users',
    }
    for name, sql in checks.items():
        assert _scalar(db_url, sql) == '1', f'Schema bootstrap check failed: {name}'
    for schema in ('public', 'default'):
        revision = _scalar(db_url, f'SELECT version_num FROM "{schema}".alembic_version')
        assert revision == expected_revision, f'{schema} schema is at {revision!r}, expected {expected_revision!r}'


def wait_for_runtime_registration(db_url: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        live = {
            kind: int(_scalar(db_url, 'SELECT count(*) FROM public.runtime_workers WHERE kind = %s AND stopped_at IS NULL', (kind,)))
            for kind in ('coordinator', 'scheduler')
        }
        if all(live.values()):
            return
        time.sleep(1)
    raise AssertionError('Timed out waiting for runtime coordinator and scheduler registration')


def _login(client: httpx.Client, email: str, password: str) -> None:
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    token = response.cookies.get('session_token')
    assert token, 'Login returned no session token'
    client.headers['X-Session-Token'] = token


def _create_analysis(client: httpx.Client) -> tuple[dict[str, object], str]:
    upload = client.post(
        '/api/v1/datasource/upload',
        files={'file': ('runtime-bootstrap-ds.csv', _SAMPLE_CSV.encode(), 'text/csv')},
        data={'name': 'runtime-bootstrap-ds'},
    )
    assert upload.status_code == 200, upload.text
    output_id = str(uuid.uuid4())
    tab = {
        'id': str(uuid.uuid4()),
        'name': 'Source 1',
        'parent_id': None,
        'datasource': {'id': upload.json()['id'], 'analysis_tab_id': None, 'config': {'branch': 'master'}},
        'output': {
            'result_id': output_id,
            'datasource_type': 'iceberg',
            'format': 'parquet',
            'filename': 'source_1',
            'build_mode': 'full',
            'iceberg': {'namespace': 'outputs', 'table_name': 'source_1', 'branch': 'master'},
        },
        'steps': [{'id': str(uuid.uuid4()), 'type': 'view', 'config': {}, 'depends_on': [], 'is_applied': True}],
    }
    response = client.post('/api/v1/analysis', json={'name': 'Runtime Bootstrap Analysis', 'description': None, 'tabs': [tab]})
    assert response.status_code == 200, response.text
    return dict(response.json()), output_id


def _run_manual_build(client: httpx.Client, analysis: dict[str, object]) -> str:
    pipeline = analysis['pipeline_definition']
    assert isinstance(pipeline, dict)
    response = client.post(
        '/api/v1/compute/builds',
        json={'analysis_pipeline': {'analysis_id': analysis['id'], **pipeline}, 'tab_id': pipeline['tabs'][0]['id']},
    )
    assert response.status_code == 200, response.text
    build_id = str(response.json()['build_id'])
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        detail = client.get(f'/api/v1/compute/builds/{build_id}')
        if detail.status_code == 200 and detail.json().get('status') in _TERMINAL_BUILD_STATUSES:
            status = detail.json()['status']
            assert status == 'completed', f'Manual build {build_id} ended {status}: {detail.text}'
            return build_id
        time.sleep(1)
    raise AssertionError(f'Timed out waiting for manual build {build_id}')


def _wait_for_scheduled_build(db_url: str, schedule_id: str) -> tuple[str, str]:
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        failure = _scalar(db_url, 'SELECT last_failure_at::text FROM "default".schedules WHERE id = %s', (schedule_id,))
        assert not failure, f'Scheduled build enqueue failed for {schedule_id} at {failure}'
        row = _scalar(
            db_url,
            "SELECT concat(id, '|', status) FROM \"default\".build_runs WHERE schedule_id = %s ORDER BY created_at DESC LIMIT 1",
            (schedule_id,),
        )
        if row:
            build_id, status = row.split('|', maxsplit=1)
            if status in _TERMINAL_BUILD_STATUSES:
                return build_id, status
        time.sleep(1)
    schedule_state = _scalar(
        db_url,
        "SELECT concat(enabled, '|', COALESCE(next_run::text, ''), '|', COALESCE(lease_owner, '')) FROM \"default\".schedules WHERE id = %s",
        (schedule_id,),
    )
    workers = _scalar(
        db_url,
        "SELECT string_agg(concat(kind, ':', id, ':', active_jobs, ':', COALESCE(stopped_at::text, '')), ',') FROM public.runtime_workers",
    )
    raise AssertionError(f'Timed out waiting for scheduled build {schedule_id}; schedule={schedule_state}; workers={workers}')


def check_manual_and_scheduled_builds(api_url: str, db_url: str, email: str, password: str) -> None:
    with httpx.Client(base_url=api_url, timeout=30) as client:
        _login(client, email, password)
        analysis, output_id = _create_analysis(client)
        manual_build_id = _run_manual_build(client, analysis)
        # A yearly cron keeps the scheduler from firing on its own; the probe moves next_run into the past instead.
        schedule = client.post('/api/v1/schedules', json={'datasource_id': output_id, 'cron_expression': '0 0 1 1 *', 'enabled': True})
        assert schedule.status_code == 200, schedule.text
        schedule_id = str(schedule.json()['id'])

        run_at = (datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None)
        with psycopg.connect(db_url, autocommit=True) as connection:
            connection.execute('UPDATE "default".schedules SET next_run = %s WHERE id = %s', (run_at, schedule_id))

        scheduled_build_id, status = _wait_for_scheduled_build(db_url, schedule_id)
        assert status == 'completed', f'Scheduled build {scheduled_build_id} ended {status}'
        assert scheduled_build_id != manual_build_id
        client.delete(f'/api/v1/schedules/{schedule_id}').raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--db-url', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--expected-revision', required=True)
    args = parser.parse_args()

    check_schema_bootstrap(args.db_url, args.expected_revision)
    print('Schema bootstrap: ok', flush=True)
    wait_for_runtime_registration(args.db_url)
    check_manual_and_scheduled_builds(args.api_url, args.db_url, args.email, args.password)
    print('Manual and scheduler-fired builds: ok', flush=True)


if __name__ == '__main__':
    main()
