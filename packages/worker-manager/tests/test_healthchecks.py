import uuid
from datetime import UTC, datetime, timedelta

import polars as pl
from contracts.compute.schemas import BuildStatus
from contracts.datasource.models import DataSource
from contracts.healthcheck_models import HealthCheck, HealthCheckResult
from core.healthcheck_runner import run_healthchecks

from runtime.compute_service import _build_subscriber_message, _resolve_build_status


def _create_datasource(session, ds_id: str | None = None) -> DataSource:
    datasource_id = ds_id or str(uuid.uuid4())
    datasource = DataSource(
        id=datasource_id,
        name="Health Source",
        source_type="file",
        config={"file_path": "/tmp/file.csv", "file_type": "csv", "options": {}},
        created_at=datetime.now(UTC),
    )
    session.add(datasource)
    session.commit()
    return datasource


def _make_check(
    datasource_id: str,
    check_type: str = "row_count",
    config: dict | None = None,
    name: str = "Test Check",
    critical: bool = False,
) -> HealthCheck:
    return HealthCheck(
        id=str(uuid.uuid4()),
        datasource_id=datasource_id,
        name=name,
        check_type=check_type,
        config=config or {"min_rows": 1},
        enabled=True,
        critical=critical,
        created_at=datetime.now(UTC),
    )


def _create_check(session, datasource_id: str, name: str = "Row Count Check") -> HealthCheck:
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
        details={"min_rows": 1},
        checked_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


SAMPLE_LF = pl.LazyFrame(
    {
        "id": [1, 2, 3, 4, 5],
        "name": ["a", "b", None, "d", "e"],
        "value": [10.0, 20.0, 30.0, 40.0, 50.0],
    },
)


class TestRunHealthchecks:
    def test_empty_checks(self, test_db_session):
        results = run_healthchecks(test_db_session, [], SAMPLE_LF)
        assert results == []

    def test_row_count_pass(self, test_db_session):
        check = _make_check("ds-1", config={"min_rows": 1, "max_rows": 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert "Row count: 5" in results[0].message
        assert results[0].details["actual_count"] == 5

    def test_row_count_fail(self, test_db_session):
        check = _make_check("ds-1", config={"min_rows": 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Too few" in results[0].message

    def test_column_null_pass(self, test_db_session):
        check = _make_check("ds-1", check_type="column_null", config={"column": "name", "threshold": 25})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert "Nulls: 20.0%" in results[0].message

    def test_column_null_fail(self, test_db_session):
        check = _make_check("ds-1", check_type="column_null", config={"column": "name", "threshold": 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False

    def test_column_unique(self, test_db_session):
        check = _make_check(
            "ds-1",
            check_type="column_unique",
            config={"column": "id", "expected_unique": 5},
        )
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].details["actual_unique"] == 5

    def test_column_range_pass(self, test_db_session):
        check = _make_check(
            "ds-1",
            check_type="column_range",
            config={"column": "value", "min": 0, "max": 100},
        )
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True

    def test_column_range_fail(self, test_db_session):
        check = _make_check(
            "ds-1",
            check_type="column_range",
            config={"column": "value", "min": 0, "max": 25},
        )
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False
        assert "Max" in results[0].message

    def test_missing_column_immediate_failure(self, test_db_session):
        check = _make_check(
            "ds-1",
            check_type="column_null",
            config={"column": "nonexistent", "threshold": 10},
        )
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is False
        assert "not found" in results[0].message

    def test_batch_single_collect(self, test_db_session):
        checks = [
            _make_check("ds-1", check_type="row_count", config={"min_rows": 1}, name="Row"),
            _make_check(
                "ds-1",
                check_type="column_null",
                config={"column": "name", "threshold": 50},
                name="Null",
            ),
            _make_check(
                "ds-1",
                check_type="column_range",
                config={"column": "value", "min": 0, "max": 100},
                name="Range",
            ),
            _make_check(
                "ds-1",
                check_type="column_count",
                config={"min_columns": 3},
                name="Columns",
            ),
            _make_check(
                "ds-1",
                check_type="null_percentage",
                config={"threshold": 30},
                name="Nulls Overall",
            ),
            _make_check(
                "ds-1",
                check_type="duplicate_percentage",
                config={"threshold": 10},
                name="Duplicates",
            ),
        ]
        for c in checks:
            test_db_session.add(c)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, checks, SAMPLE_LF)
        assert len(results) == 6
        assert all(r.passed for r in results)

    def test_batch_mixed_pass_fail(self, test_db_session):
        checks = [
            _make_check("ds-1", check_type="row_count", config={"min_rows": 100}, name="Fail"),
            _make_check(
                "ds-1",
                check_type="column_null",
                config={"column": "name", "threshold": 50},
                name="Pass",
            ),
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
        check = _make_check("ds-1", check_type="null_percentage", config={"threshold": 30})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert "Nulls:" in results[0].message

    def test_null_percentage_zero_column_dataset(self, test_db_session):
        check = _make_check("ds-1", check_type="null_percentage", config={"threshold": 30})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], pl.DataFrame(schema={}).lazy())

        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].message == "Nulls: 0.0% (threshold: 30.0%)"
        assert results[0].details["actual_percentage"] == 0.0

    def test_duplicate_percentage(self, test_db_session):
        check = _make_check("ds-1", check_type="duplicate_percentage", config={"threshold": 10})
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True
        assert "Duplicates:" in results[0].message

    def test_column_count(self, test_db_session):
        check = _make_check(
            "ds-1",
            check_type="column_count",
            config={"min_columns": 3, "max_columns": 5},
        )
        test_db_session.add(check)
        test_db_session.flush()

        results = run_healthchecks(test_db_session, [check], SAMPLE_LF)
        assert len(results) == 1
        assert results[0].passed is True

    def test_critical_only(self, test_db_session):
        checks = [
            _make_check(
                "ds-1",
                check_type="row_count",
                config={"min_rows": 100},
                name="Fail",
                critical=True,
            ),
            _make_check(
                "ds-1",
                check_type="column_null",
                config={"column": "name", "threshold": 50},
                name="Pass",
            ),
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
        assert status is BuildStatus.SUCCESS
        assert summary is None
        assert details is None

    def test_all_pass(self):
        results = [
            HealthCheckResult(
                id="r1",
                healthcheck_id="c1",
                passed=True,
                message="ok",
                details={},
                checked_at=datetime.now(UTC),
            ),
            HealthCheckResult(
                id="r2",
                healthcheck_id="c2",
                passed=True,
                message="ok",
                details={},
                checked_at=datetime.now(UTC),
            ),
        ]
        status, summary, details = _resolve_build_status(results)
        assert status is BuildStatus.SUCCESS
        assert summary == "2/2 passed"
        assert details is None

    def test_some_fail(self):
        results = [
            HealthCheckResult(
                id="r1",
                healthcheck_id="c1",
                passed=True,
                message="ok",
                details={},
                checked_at=datetime.now(UTC),
            ),
            HealthCheckResult(
                id="r2",
                healthcheck_id="c2",
                passed=False,
                message="bad",
                details={},
                checked_at=datetime.now(UTC),
            ),
        ]
        status, summary, details = _resolve_build_status(results)
        assert status is BuildStatus.WARNING
        assert summary == "1/2 failed"
        assert details is not None
        assert len(details) == 2

    def test_critical_fail_ignored(self):
        check = HealthCheck(
            id="c1",
            datasource_id="ds-1",
            name="Critical Check",
            check_type="row_count",
            config={},
            enabled=True,
            critical=True,
            created_at=datetime.now(UTC),
        )
        results = [
            HealthCheckResult(
                id="r1",
                healthcheck_id="c1",
                passed=False,
                message="bad",
                details={},
                checked_at=datetime.now(UTC),
            ),
        ]
        status, summary, details = _resolve_build_status(results, [check])
        assert status is BuildStatus.WARNING
        assert summary == "1/1 failed"
        assert details is not None

    def test_uses_check_name_not_id(self):
        check = HealthCheck(
            id="c1",
            datasource_id="ds-1",
            name="Row Guard",
            check_type="row_count",
            config={},
            enabled=True,
            critical=False,
            created_at=datetime.now(UTC),
        )
        results = [
            HealthCheckResult(
                id="r1",
                healthcheck_id="c1",
                passed=False,
                message="bad",
                details={},
                checked_at=datetime.now(UTC),
            ),
        ]
        _, _, details = _resolve_build_status(results, [check])
        assert details is not None
        assert details[0].name == "Row Guard"
        assert details[0].critical is False


class TestBuildSubscriberMessage:
    def test_no_healthchecks(self):
        msg = _build_subscriber_message(
            {
                "status": BuildStatus.SUCCESS,
                "analysis_name": "Test",
                "row_count": "100",
                "duration_ms": "500",
                "healthcheck_summary": None,
                "healthcheck_details": None,
            },
        )
        assert "Status: success" in msg
        assert "Rows: 100" in msg
        assert "health check" not in msg.lower()

    def test_all_pass(self):
        msg = _build_subscriber_message(
            {
                "status": BuildStatus.SUCCESS,
                "analysis_name": "Test",
                "row_count": "100",
                "duration_ms": "500",
                "healthcheck_summary": "2/2 passed",
                "healthcheck_details": None,
            },
        )
        assert "Status: success" in msg
        assert "2/2 passed" in msg

    def test_some_fail(self):
        msg = _build_subscriber_message(
            {
                "status": BuildStatus.WARNING,
                "analysis_name": "Test",
                "row_count": "100",
                "duration_ms": "500",
                "healthcheck_summary": "1/2 failed",
                "healthcheck_details": [
                    {"name": "check-1", "passed": True, "message": "ok"},
                    {"name": "check-2", "passed": False, "message": "bad"},
                ],
            },
        )
        assert "built successfully, health checks failed" in msg
        assert "1/2 failed" in msg

    def test_long_message_truncates(self):
        details = [{"name": f"check-{i}", "passed": False, "message": "bad"} for i in range(300)]
        msg = _build_subscriber_message(
            {
                "status": BuildStatus.WARNING,
                "analysis_name": "Test",
                "row_count": "100",
                "duration_ms": "500",
                "healthcheck_summary": "300/300 failed",
                "healthcheck_details": details,
            },
        )
        assert len(msg) <= 3815
