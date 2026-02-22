import uuid
from datetime import UTC, datetime, timedelta

import polars as pl

from modules.compute.service import _build_subscriber_message, _resolve_build_status
from modules.datasource.models import DataSource
from modules.healthcheck.models import HealthCheck, HealthCheckResult
from modules.healthcheck.service import run_healthchecks


def _create_datasource(session, ds_id: str | None = None) -> DataSource:
    datasource_id = ds_id or str(uuid.uuid4())
    datasource = DataSource(
        id=datasource_id,
        name='Health Source',
        source_type='file',
        config={'file_path': '/tmp/file.csv', 'file_type': 'csv', 'options': {}},
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    return datasource


def _make_check(
    datasource_id: str,
    check_type: str = 'row_count',
    config: dict | None = None,
    name: str = 'Test Check',
    critical: bool = False,
) -> HealthCheck:
    return HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=datasource_id,
        name=name,
        check_type=check_type,
        config=config or {'min_rows': 1},
        enabled=True,
        critical=critical,
        created_at=datetime.now(UTC),
    )


def _create_check(session, datasource_id: str, name: str = 'Row Count Check') -> HealthCheck:
    check = _make_check(datasource_id, name=name)
    session.add(check)
    session.commit()
    session.refresh(check)
    return check


def _create_result(session, healthcheck_id: str, passed: bool, message: str, minutes_ago: int = 0) -> HealthCheckResult:
    result = HealthCheckResult(
        id=str(uuid.uuid4()),
        healthcheck_id=healthcheck_id,
        passed=passed,
        message=message,
        details={'min_rows': 1},
        checked_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


SAMPLE_LF = pl.LazyFrame(
    {
        'id': [1, 2, 3, 4, 5],
        'name': ['a', 'b', None, 'd', 'e'],
        'value': [10.0, 20.0, 30.0, 40.0, 50.0],
    }
)


class TestRunHealthchecks:
    def test_empty_checks(self, test_db_session):
        results = run_healthchecks(test_db_session, [], SAMPLE_LF)
        assert results == []

    def test_row_count_pass(self, test_db_session):
        check = _make_check('ds-1', config={'min_rows': 1, 'max_rows': 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert 'Row count: 5' in results[0].message
        assert results[0].details['actual_count'] == 5

    def test_row_count_fail(self, test_db_session):
        check = _make_check('ds-1', config={'min_rows': 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False
        assert 'Too few' in results[0].message

    def test_column_null_pass(self, test_db_session):
        check = _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 25})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert 'Nulls: 20.0%' in results[0].message

    def test_column_null_fail(self, test_db_session):
        check = _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False

    def test_column_unique(self, test_db_session):
        check = _make_check('ds-1', check_type='column_unique', config={'column': 'id', 'expected_unique': 5})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].details['actual_unique'] == 5

    def test_column_range_pass(self, test_db_session):
        check = _make_check('ds-1', check_type='column_range', config={'column': 'value', 'min': 0, 'max': 100})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True

    def test_column_range_fail(self, test_db_session):
        check = _make_check('ds-1', check_type='column_range', config={'column': 'value', 'min': 0, 'max': 25})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False
        assert 'Max' in results[0].message

    def test_missing_column_immediate_failure(self, test_db_session):
        check = _make_check('ds-1', check_type='column_null', config={'column': 'nonexistent', 'threshold': 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False
        assert 'not found' in results[0].message

    def test_batch_single_collect(self, test_db_session):
        checks = [
            _make_check('ds-1', check_type='row_count', config={'min_rows': 1}, name='Row'),
            _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 50}, name='Null'),
            _make_check('ds-1', check_type='column_range', config={'column': 'value', 'min': 0, 'max': 100}, name='Range'),
            _make_check('ds-1', check_type='column_count', config={'min_columns': 3}, name='Columns'),
            _make_check('ds-1', check_type='null_percentage', config={'threshold': 30}, name='Nulls Overall'),
            _make_check('ds-1', check_type='duplicate_percentage', config={'threshold': 10}, name='Duplicates'),
        ]
        for c in checks:
            test_db_session.add(c)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, checks, SAMPLE_LF)
        assert len(results) == 6
        assert all(r.passed for r in results)

    def test_batch_mixed_pass_fail(self, test_db_session):
        checks = [
            _make_check('ds-1', check_type='row_count', config={'min_rows': 100}, name='Fail'),
            _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 50}, name='Pass'),
        ]
        for c in checks:
            test_db_session.add(c)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, checks, SAMPLE_LF)
        assert len(results) == 2
        by_name = {r.healthcheck_id: r for r in results}
        assert by_name[checks[0].id].passed is False
        assert by_name[checks[1].id].passed is True

    def test_null_percentage(self, test_db_session):
        check = _make_check('ds-1', check_type='null_percentage', config={'threshold': 30})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert 'Nulls:' in results[0].message

    def test_duplicate_percentage(self, test_db_session):
        check = _make_check('ds-1', check_type='duplicate_percentage', config={'threshold': 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert 'Duplicates:' in results[0].message

    def test_column_count(self, test_db_session):
        check = _make_check('ds-1', check_type='column_count', config={'min_columns': 3, 'max_columns': 5})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True

    def test_critical_only(self, test_db_session):
        checks = [
            _make_check('ds-1', check_type='row_count', config={'min_rows': 100}, name='Fail', critical=True),
            _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 50}, name='Pass'),
        ]
        for check in checks:
            test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, checks, SAMPLE_LF, critical_only=True)
        assert len(results) == 1
        assert results[0].healthcheck_id == checks[0].id
        assert results[0].passed is False


class TestResolveBuildStatus:
    def test_no_results(self):
        status, summary, details = _resolve_build_status([])
        assert status == 'success'
        assert summary is None
        assert details is None

    def test_all_pass(self):
        results = [
            HealthCheckResult(id='r1', healthcheck_id='c1', passed=True, message='ok', details={}, checked_at=datetime.now(UTC)),
            HealthCheckResult(id='r2', healthcheck_id='c2', passed=True, message='ok', details={}, checked_at=datetime.now(UTC)),
        ]
        status, summary, details = _resolve_build_status(results)
        assert status == 'success'
        assert summary == '2/2 passed'
        assert details is None

    def test_some_fail(self):
        results = [
            HealthCheckResult(id='r1', healthcheck_id='c1', passed=True, message='ok', details={}, checked_at=datetime.now(UTC)),
            HealthCheckResult(id='r2', healthcheck_id='c2', passed=False, message='bad', details={}, checked_at=datetime.now(UTC)),
        ]
        status, summary, details = _resolve_build_status(results)
        assert status == 'warning'
        assert summary == '1/2 failed'
        assert details is not None
        assert len(details) == 2

    def test_critical_fail_ignored(self):
        check = HealthCheck(
            id='c1',
            datasource_id='ds-1',
            name='Critical Check',
            check_type='row_count',
            config={},
            enabled=True,
            critical=True,
            created_at=datetime.now(UTC),
        )
        results = [
            HealthCheckResult(id='r1', healthcheck_id='c1', passed=False, message='bad', details={}, checked_at=datetime.now(UTC)),
        ]
        status, summary, details = _resolve_build_status(results, [check])
        assert status == 'warning'
        assert summary == '1/1 failed'
        assert details is not None

    def test_uses_check_name_not_id(self):
        check = HealthCheck(
            id='c1',
            datasource_id='ds-1',
            name='Row Guard',
            check_type='row_count',
            config={},
            enabled=True,
            critical=False,
            created_at=datetime.now(UTC),
        )
        results = [
            HealthCheckResult(id='r1', healthcheck_id='c1', passed=False, message='bad', details={}, checked_at=datetime.now(UTC)),
        ]
        _, _, details = _resolve_build_status(results, [check])
        assert details is not None
        assert details[0]['name'] == 'Row Guard'
        assert details[0]['critical'] is False


class TestBuildSubscriberMessage:
    def test_no_healthchecks(self):
        msg = _build_subscriber_message(
            {
                'status': 'success',
                'analysis_name': 'Test',
                'row_count': '100',
                'duration_ms': '500',
                'healthcheck_summary': None,
                'healthcheck_details': None,
            }
        )
        assert 'Status: success' in msg
        assert 'Rows: 100' in msg
        assert 'health check' not in msg.lower()

    def test_all_pass(self):
        msg = _build_subscriber_message(
            {
                'status': 'success',
                'analysis_name': 'Test',
                'row_count': '100',
                'duration_ms': '500',
                'healthcheck_summary': '2/2 passed',
                'healthcheck_details': None,
            }
        )
        assert 'Status: success' in msg
        assert '2/2 passed' in msg

    def test_some_fail(self):
        msg = _build_subscriber_message(
            {
                'status': 'warning',
                'analysis_name': 'Test',
                'row_count': '100',
                'duration_ms': '500',
                'healthcheck_summary': '1/2 failed',
                'healthcheck_details': [
                    {'name': 'check-1', 'passed': True, 'message': 'ok'},
                    {'name': 'check-2', 'passed': False, 'message': 'bad'},
                ],
            }
        )
        assert 'built successfully, health checks failed' in msg
        assert '1/2 failed' in msg

    def test_long_message_truncates(self):
        details = [{'name': f'check-{i}', 'passed': False, 'message': 'bad'} for i in range(300)]
        msg = _build_subscriber_message(
            {
                'status': 'warning',
                'analysis_name': 'Test',
                'row_count': '100',
                'duration_ms': '500',
                'healthcheck_summary': '300/300 failed',
                'healthcheck_details': details,
            }
        )
        assert len(msg) <= 3815


def test_healthcheck_crud(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)

    create_payload = {
        'datasource_id': datasource_id,
        'name': 'Row Count Check',
        'check_type': 'row_count',
        'config': {'min_rows': 1},
        'enabled': True,
        'critical': True,
    }
    create_response = client.post('/api/v1/healthchecks', json=create_payload)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created['name'] == 'Row Count Check'
    assert created['critical'] is True

    duplicate_response = client.post('/api/v1/healthchecks', json=create_payload)
    assert duplicate_response.status_code == 400

    list_response = client.get(f'/api/v1/healthchecks?datasource_id={datasource_id}')
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1

    update_response = client.put(
        f'/api/v1/healthchecks/{created["id"]}',
        json={'name': 'Updated Check', 'enabled': False, 'critical': False},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated['name'] == 'Updated Check'
    assert updated['enabled'] is False
    assert updated['critical'] is False

    delete_response = client.delete(f'/api/v1/healthchecks/{created["id"]}')
    assert delete_response.status_code == 204


def test_healthcheck_update_duplicate_row_count(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)

    first_payload = {
        'datasource_id': datasource_id,
        'name': 'Row Count Check',
        'check_type': 'row_count',
        'config': {'min_rows': 1},
        'enabled': True,
        'critical': False,
    }
    first_response = client.post('/api/v1/healthchecks', json=first_payload)
    assert first_response.status_code == 200
    second_id = str(uuid.uuid4())
    test_db_session.add(
        HealthCheck(
            id=second_id,
            datasource_id=datasource_id,
            name='Column Null Check',
            check_type='column_null',
            config={'column': 'name', 'threshold': 10},
            enabled=True,
            critical=False,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()

    update_response = client.put(
        f'/api/v1/healthchecks/{second_id}',
        json={'check_type': 'row_count'},
    )
    assert update_response.status_code == 400


def test_list_results_empty(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    _create_check(test_db_session, datasource_id)

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}')
    assert response.status_code == 200
    assert response.json() == []


def test_list_results_after_run(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)
    _create_result(test_db_session, check.id, True, 'Row count: 42')

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['healthcheck_id'] == check.id
    assert data[0]['passed'] is True
    assert data[0]['message'] == 'Row count: 42'


def test_list_results_limit(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)

    for i in range(5):
        _create_result(test_db_session, check.id, True, f'Result {i}', minutes_ago=i)

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}&limit=3')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_list_results_ordering(test_db_session, client):
    datasource_id = str(uuid.uuid4())
    _create_datasource(test_db_session, datasource_id)
    check = _create_check(test_db_session, datasource_id)

    _create_result(test_db_session, check.id, False, 'Old failure', minutes_ago=10)
    _create_result(test_db_session, check.id, True, 'Recent success', minutes_ago=0)

    response = client.get(f'/api/v1/healthchecks/results?datasource_id={datasource_id}')
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]['message'] == 'Recent success'
    assert data[1]['message'] == 'Old failure'


def test_list_results_no_datasource(client):
    missing_id = str(uuid.uuid4())
    response = client.get(f'/api/v1/healthchecks/results?datasource_id={missing_id}')
    assert response.status_code == 200
    assert response.json() == []


def test_list_results_invalid_uuid(client):
    response = client.get('/api/v1/healthchecks/results?datasource_id=nonexistent')
    assert response.status_code == 400
