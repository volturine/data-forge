import uuid
from datetime import UTC, datetime

from contracts.engine_runs.models import EngineRun
from sqlmodel import Session


def _create_run(
    session: Session,
    *,
    datasource_id: str | None = None,
    kind: str = "download",
    status: str = "success",
    result_json: dict | None = None,
    step_timings: dict | None = None,
    duration_ms: int | None = None,
) -> EngineRun:
    run = EngineRun(
        id=str(uuid.uuid4()),
        analysis_id=str(uuid.uuid4()),
        datasource_id=datasource_id or str(uuid.uuid4()),
        kind=kind,
        status=status,
        request_json={},
        result_json=result_json,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        step_timings=step_timings or {},
        progress=1.0,
        duration_ms=duration_ms,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


class TestCompareEndpoint:
    def test_compare_endpoint(self, client, test_db_session: Session) -> None:
        run_a = _create_run(
            test_db_session,
            result_json={"schema": {"x": "Int64"}, "row_count": 10},
            step_timings={"s1": 50},
            duration_ms=50,
        )
        run_b = EngineRun(
            id=str(uuid.uuid4()),
            analysis_id=run_a.analysis_id,
            datasource_id=run_a.datasource_id,
            kind="download",
            status="success",
            request_json={},
            result_json={"schema": {"x": "Int64", "y": "Utf8"}, "row_count": 20},
            created_at=datetime.now(UTC).replace(tzinfo=None),
            step_timings={"s1": 60},
            progress=1.0,
            duration_ms=60,
        )
        test_db_session.add(run_b)
        test_db_session.commit()
        test_db_session.refresh(run_b)

        resp = client.get(
            "/api/v1/engine-runs/compare",
            params={"run_a": run_a.id, "run_b": run_b.id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["row_count_a"] == 10
        assert data["row_count_b"] == 20
        assert data["row_count_delta"] == 10
        assert data["total_duration_delta_ms"] == 10
        assert len(data["schema_diff"]) == 1
        assert data["schema_diff"][0]["column"] == "y"
        assert data["schema_diff"][0]["status"] == "added"

    def test_compare_endpoint_not_found(self, client) -> None:
        resp = client.get(
            "/api/v1/engine-runs/compare",
            params={"run_a": "fake-a", "run_b": "fake-b"},
        )
        assert resp.status_code == 400

    def test_compare_endpoint_datasource_mismatch(self, client, test_db_session: Session) -> None:
        run_a = _create_run(test_db_session, result_json={"row_count": 10})
        run_b = _create_run(test_db_session, result_json={"row_count": 20})
        resp = client.get(
            "/api/v1/engine-runs/compare",
            params={
                "run_a": run_a.id,
                "run_b": run_b.id,
                "datasource_id": run_a.datasource_id,
            },
        )
        assert resp.status_code == 400
