"""Healthcheck persistence and pure evaluation tests.

Polars-backed healthcheck execution lives on the worker. Backend owns check
CRUD and the pure evaluate() policy that turns collected metric maps into
pass/fail results.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend_core.persistence.datasource.models import DataSource
from backend_core.persistence.healthchecks.models import HealthCheck, HealthCheckResult


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


class TestHealthCheckEvaluate:
    def test_row_count_pass(self) -> None:
        check = _make_check('ds-1', config={'min_rows': 1, 'max_rows': 10})
        passed, message, details = check.evaluate(values={check.metric_alias('count'): 5}, schema_names={'id'})
        assert passed is True
        assert 'Row count: 5' in message
        assert details['actual_count'] == 5

    def test_row_count_fail(self) -> None:
        check = _make_check('ds-1', config={'min_rows': 10})
        passed, message, _details = check.evaluate(values={check.metric_alias('count'): 5}, schema_names={'id'})
        assert passed is False
        assert 'Too few' in message

    def test_column_null_pass(self) -> None:
        check = _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 50})
        passed, message, details = check.evaluate(values={check.metric_alias('null_pct'): 20.0}, schema_names={'name'})
        assert passed is True
        assert 'Nulls: 20.0%' in message
        assert details['actual_percentage'] == 20.0

    def test_column_null_fail(self) -> None:
        check = _make_check('ds-1', check_type='column_null', config={'column': 'name', 'threshold': 10})
        passed, _message, _details = check.evaluate(values={check.metric_alias('null_pct'): 20.0}, schema_names={'name'})
        assert passed is False

    def test_column_unique(self) -> None:
        check = _make_check('ds-1', check_type='column_unique', config={'column': 'id', 'expected_unique': 5})
        passed, message, details = check.evaluate(values={check.metric_alias('unique'): 5}, schema_names={'id'})
        assert passed is True
        assert details['actual_unique'] == 5
        assert 'Unique: 5' in message or 'Unique values: 5' in message

    def test_column_range_pass(self) -> None:
        check = _make_check('ds-1', check_type='column_range', config={'column': 'value', 'min': 0, 'max': 100})
        passed, _message, _details = check.evaluate(
            values={check.metric_alias('min'): 10.0, check.metric_alias('max'): 50.0},
            schema_names={'value'},
        )
        assert passed is True

    def test_column_range_fail(self) -> None:
        check = _make_check('ds-1', check_type='column_range', config={'column': 'value', 'min': 0, 'max': 20})
        passed, message, _details = check.evaluate(
            values={check.metric_alias('min'): 10.0, check.metric_alias('max'): 50.0},
            schema_names={'value'},
        )
        assert passed is False
        assert 'max' in message.lower() or '50' in message

    def test_missing_column_immediate_failure(self) -> None:
        check = _make_check('ds-1', check_type='column_null', config={'column': 'missing'})
        result = check.missing_column_result(now=datetime.now(UTC))
        assert result.passed is False
        assert 'not found' in result.message

    def test_null_percentage(self) -> None:
        check = _make_check('ds-1', check_type='null_percentage', config={'threshold': 30})
        passed, message, details = check.evaluate(values={check.metric_alias('null_pct'): 20.0}, schema_names={'id', 'name'})
        assert passed is True
        assert details['actual_percentage'] == 20.0
        assert 'Nulls' in message or '20' in message

    def test_duplicate_percentage(self) -> None:
        check = _make_check('ds-1', check_type='duplicate_percentage', config={'threshold': 50, 'columns': ['id']})
        passed, message, details = check.evaluate(
            values={check.metric_alias('rows'): 5, check.metric_alias('unique_rows'): 5},
            schema_names={'id'},
        )
        assert passed is True
        assert details['actual_percentage'] == 0.0
        assert 'Duplicates: 0.0%' in message

    def test_column_count(self) -> None:
        check = _make_check('ds-1', check_type='column_count', config={'min_columns': 2, 'max_columns': 5})
        passed, message, details = check.evaluate(values={}, schema_names={'id', 'name', 'value'})
        assert passed is True
        assert details['actual_count'] == 3
        assert 'Column count: 3' in message


class TestHealthCheckPersistence:
    def test_create_and_list_results(self, test_db_session) -> None:
        datasource = _create_datasource(test_db_session)
        check = _create_check(test_db_session, datasource.id)
        result = _create_result(test_db_session, check.id, passed=True, message='ok')
        loaded = test_db_session.get(HealthCheckResult, result.id)
        assert loaded is not None
        assert loaded.passed is True
        assert loaded.healthcheck_id == check.id
