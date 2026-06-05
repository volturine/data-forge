from datetime import UTC, datetime
from types import SimpleNamespace

from runtime.compute_service import _build_subscriber_message, _resolve_build_status
from worker_models.compute.schemas import BuildStatus


def _result(healthcheck_id: str, *, passed: bool, message: str):
    return SimpleNamespace(
        healthcheck_id=healthcheck_id,
        passed=passed,
        message=message,
        details={},
        checked_at=datetime.now(UTC),
    )


class TestResolveBuildStatus:
    def test_no_results(self):
        status, summary, details = _resolve_build_status([])
        assert status is BuildStatus.SUCCESS
        assert summary is None
        assert details is None

    def test_all_pass(self):
        results = [
            _result("c1", passed=True, message="ok"),
            _result("c2", passed=True, message="ok"),
        ]
        status, summary, details = _resolve_build_status(results)
        assert status is BuildStatus.SUCCESS
        assert summary == "2/2 passed"
        assert details is None

    def test_some_fail(self):
        results = [
            _result("c1", passed=True, message="ok"),
            _result("c2", passed=False, message="bad"),
        ]
        status, summary, details = _resolve_build_status(results)
        assert status is BuildStatus.WARNING
        assert summary == "1/2 failed"
        assert details is not None
        assert len(details) == 2

    def test_critical_fail_ignored(self):
        check = SimpleNamespace(id="c1", name="Critical Check", critical=True)
        results = [_result("c1", passed=False, message="bad")]
        status, summary, details = _resolve_build_status(results, [check])
        assert status is BuildStatus.WARNING
        assert summary == "1/1 failed"
        assert details is not None

    def test_uses_check_name_not_id(self):
        check = SimpleNamespace(id="c1", name="Row Guard", critical=False)
        results = [_result("c1", passed=False, message="bad")]
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
