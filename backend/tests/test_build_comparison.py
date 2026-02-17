"""Tests for the build comparison endpoint and service."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from modules.engine_runs.models import EngineRun
from modules.engine_runs.service import (
    _compute_schema_diff,
    _compute_timing_diff,
    _safe_int,
    compare_engine_runs,
)


def _create_run(
    session: Session,
    *,
    kind: str = 'export',
    status: str = 'success',
    result_json: dict | None = None,
    step_timings: dict | None = None,
    duration_ms: int | None = None,
) -> EngineRun:
    run = EngineRun(
        id=str(uuid.uuid4()),
        analysis_id=str(uuid.uuid4()),
        datasource_id=str(uuid.uuid4()),
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


class TestSafeInt:
    def test_none(self) -> None:
        assert _safe_int(None) is None

    def test_int(self) -> None:
        assert _safe_int(42) == 42

    def test_str_int(self) -> None:
        assert _safe_int('100') == 100

    def test_invalid(self) -> None:
        assert _safe_int('abc') is None


class TestSchemasDiff:
    def test_no_changes(self) -> None:
        a = {'col_a': 'Int64', 'col_b': 'Utf8'}
        b = {'col_a': 'Int64', 'col_b': 'Utf8'}
        assert _compute_schema_diff(a, b) == []

    def test_added_column(self) -> None:
        a = {'col_a': 'Int64'}
        b = {'col_a': 'Int64', 'col_b': 'Utf8'}
        diffs = _compute_schema_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0].column == 'col_b'
        assert diffs[0].status == 'added'
        assert diffs[0].type_b == 'Utf8'
        assert diffs[0].type_a is None

    def test_removed_column(self) -> None:
        a = {'col_a': 'Int64', 'col_b': 'Utf8'}
        b = {'col_a': 'Int64'}
        diffs = _compute_schema_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0].column == 'col_b'
        assert diffs[0].status == 'removed'
        assert diffs[0].type_a == 'Utf8'
        assert diffs[0].type_b is None

    def test_type_changed(self) -> None:
        a = {'col_a': 'Int64'}
        b = {'col_a': 'Float64'}
        diffs = _compute_schema_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0].status == 'type_changed'
        assert diffs[0].type_a == 'Int64'
        assert diffs[0].type_b == 'Float64'

    def test_empty_schemas(self) -> None:
        assert _compute_schema_diff({}, {}) == []

    def test_mixed_changes(self) -> None:
        a = {'keep': 'Int64', 'removed': 'Utf8', 'changed': 'Int32'}
        b = {'keep': 'Int64', 'added': 'Boolean', 'changed': 'Int64'}
        diffs = _compute_schema_diff(a, b)
        by_col = {d.column: d for d in diffs}
        assert len(diffs) == 3
        assert by_col['added'].status == 'added'
        assert by_col['removed'].status == 'removed'
        assert by_col['changed'].status == 'type_changed'


class TestTimingDiff:
    def test_no_changes(self) -> None:
        a = {'step1': 100.0}
        b = {'step1': 100.0}
        diffs = _compute_timing_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0].delta_ms == 0.0
        assert diffs[0].delta_pct == 0.0

    def test_step_added(self) -> None:
        a: dict[str, float] = {}
        b = {'step1': 50.0}
        diffs = _compute_timing_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0].ms_a is None
        assert diffs[0].ms_b == 50.0
        assert diffs[0].delta_ms is None

    def test_step_removed(self) -> None:
        a = {'step1': 50.0}
        b: dict[str, float] = {}
        diffs = _compute_timing_diff(a, b)
        assert len(diffs) == 1
        assert diffs[0].ms_a == 50.0
        assert diffs[0].ms_b is None

    def test_delta_percentage(self) -> None:
        a = {'step1': 100.0}
        b = {'step1': 150.0}
        diffs = _compute_timing_diff(a, b)
        assert diffs[0].delta_ms == 50.0
        assert diffs[0].delta_pct == 50.0

    def test_empty(self) -> None:
        assert _compute_timing_diff({}, {}) == []


class TestCompareEngineRuns:
    def test_compare_two_runs(self, test_db_session: Session) -> None:
        run_a = _create_run(
            test_db_session,
            result_json={
                'schema': {'col_a': 'Int64', 'col_b': 'Utf8'},
                'row_count': 100,
            },
            step_timings={'filter': 50, 'select': 30},
            duration_ms=80,
        )
        run_b = _create_run(
            test_db_session,
            result_json={
                'schema': {'col_a': 'Int64', 'col_c': 'Float64'},
                'row_count': 150,
            },
            step_timings={'filter': 40, 'select': 35, 'sort': 10},
            duration_ms=85,
        )

        result = compare_engine_runs(test_db_session, run_a.id, run_b.id)

        assert result.run_a.id == run_a.id
        assert result.run_b.id == run_b.id
        assert result.row_count_a == 100
        assert result.row_count_b == 150
        assert result.row_count_delta == 50
        assert result.total_duration_delta_ms == 5

        # Schema diff: col_b removed, col_c added
        by_col = {d.column: d for d in result.schema_diff}
        assert len(result.schema_diff) == 2
        assert by_col['col_b'].status == 'removed'
        assert by_col['col_c'].status == 'added'

        # Timing diff: filter, select, sort
        by_step = {t.step: t for t in result.timing_diff}
        assert len(result.timing_diff) == 3
        assert by_step['filter'].delta_ms == -10.0
        assert by_step['sort'].ms_a is None

    def test_compare_run_not_found(self, test_db_session: Session) -> None:
        run_a = _create_run(test_db_session, result_json={})
        missing_id = str(uuid.uuid4())
        with pytest.raises(Exception, match='not found'):
            compare_engine_runs(test_db_session, run_a.id, missing_id)

    def test_compare_identical_runs(self, test_db_session: Session) -> None:
        run_a = _create_run(
            test_db_session,
            result_json={'schema': {'col_a': 'Int64'}, 'row_count': 10},
            step_timings={'step1': 100},
            duration_ms=100,
        )
        run_b = _create_run(
            test_db_session,
            result_json={'schema': {'col_a': 'Int64'}, 'row_count': 10},
            step_timings={'step1': 100},
            duration_ms=100,
        )

        result = compare_engine_runs(test_db_session, run_a.id, run_b.id)
        assert result.row_count_delta == 0
        assert result.total_duration_delta_ms == 0
        assert result.schema_diff == []
        assert len(result.timing_diff) == 1
        assert result.timing_diff[0].delta_ms == 0.0

    def test_compare_runs_without_result_json(self, test_db_session: Session) -> None:
        run_a = _create_run(test_db_session, result_json=None)
        run_b = _create_run(test_db_session, result_json=None)

        result = compare_engine_runs(test_db_session, run_a.id, run_b.id)
        assert result.row_count_a is None
        assert result.row_count_b is None
        assert result.row_count_delta is None
        assert result.schema_diff == []
        assert result.timing_diff == []

    def test_compare_row_count_as_string(self, test_db_session: Session) -> None:
        """Row count stored as string (common from engine) should be parsed."""
        run_a = _create_run(test_db_session, result_json={'row_count': '200'})
        run_b = _create_run(test_db_session, result_json={'row_count': '300'})

        result = compare_engine_runs(test_db_session, run_a.id, run_b.id)
        assert result.row_count_a == 200
        assert result.row_count_b == 300
        assert result.row_count_delta == 100


class TestCompareEndpoint:
    def test_compare_endpoint(self, client, test_db_session: Session) -> None:
        run_a = _create_run(
            test_db_session,
            result_json={'schema': {'x': 'Int64'}, 'row_count': 10},
            step_timings={'s1': 50},
            duration_ms=50,
        )
        run_b = _create_run(
            test_db_session,
            result_json={'schema': {'x': 'Int64', 'y': 'Utf8'}, 'row_count': 20},
            step_timings={'s1': 60},
            duration_ms=60,
        )

        resp = client.get(
            '/api/v1/engine-runs/compare',
            params={'run_a': run_a.id, 'run_b': run_b.id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['row_count_a'] == 10
        assert data['row_count_b'] == 20
        assert data['row_count_delta'] == 10
        assert data['total_duration_delta_ms'] == 10
        assert len(data['schema_diff']) == 1
        assert data['schema_diff'][0]['column'] == 'y'
        assert data['schema_diff'][0]['status'] == 'added'

    def test_compare_endpoint_not_found(self, client) -> None:
        resp = client.get(
            '/api/v1/engine-runs/compare',
            params={'run_a': 'fake-a', 'run_b': 'fake-b'},
        )
        assert resp.status_code == 400
