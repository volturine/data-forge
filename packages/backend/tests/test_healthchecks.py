"""Healthcheck CRUD and persistence tests. Evaluation runs on the worker."""

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


def _create_check(session, datasource_id: str, name: str = 'Row Count Check') -> HealthCheck:
    check = HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=datasource_id,
        name=name,
        check_type='row_count',
        config={'min_rows': 1},
        enabled=True,
        critical=False,
        created_at=datetime.now(UTC),
    )
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


class TestHealthCheckPersistence:
    def test_create_and_list_results(self, test_db_session) -> None:
        datasource = _create_datasource(test_db_session)
        check = _create_check(test_db_session, datasource.id)
        result = _create_result(test_db_session, check.id, passed=True, message='ok')
        loaded = test_db_session.get(HealthCheckResult, result.id)
        assert loaded is not None
        assert loaded.passed is True
        assert loaded.healthcheck_id == check.id
