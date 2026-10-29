"""Tests for the build comparison endpoint and service."""

import uuid

import pytest
from sqlmodel import Session

from backend_core.compute_worker_runs_service import _compute_schema_diff, _compute_timing_diff, _safe_int, compare_compute_worker_runs
from backend_core.exceptions import AppError, ComputeWorkerRunComparisonError
from tests.harness.compute_run_factories import create_compute_worker_run


class TestSafeInt:
    @pytest.mark.parametrize(
        ('value', 'expected'),
        [
            pytest.param(None, None, id='none'),
            pytest.param(42, 42, id='int'),
            pytest.param('100', 100, id='str-int'),
            pytest.param(12.9, 12, id='float-truncates'),
            pytest.param('abc', None, id='invalid-str'),
            pytest.param({'row_count': 10}, None, id='non-scalar'),
        ],
    )
    def test_parses_scalars_or_returns_none(self, value: object, expected: int | None) -> None:
        assert _safe_int(value) == expected


class TestSchemasDiff:
    def test_no_changes(self) -> None:
        a = {'col_a': 'Int64', 'col_b': 'Utf8'}
        b = {'col_a': 'Int64', 'col_b': 'Utf8'}
        assert _compute_schema_diff(a, b) == []

    @pytest.mark.parametrize(
        ('schema_a', 'schema_b', 'column', 'status', 'type_a', 'type_b'),
        [
            pytest.param({'col_a': 'Int64'}, {'col_a': 'Int64', 'col_b': 'Utf8'}, 'col_b', 'added', None, 'Utf8', id='added-column'),
            pytest.param({'col_a': 'Int64', 'col_b': 'Utf8'}, {'col_a': 'Int64'}, 'col_b', 'removed', 'Utf8', None, id='removed-column'),
            pytest.param({'col_a': 'Int64'}, {'col_a': 'Float64'}, 'col_a', 'type_changed', 'Int64', 'Float64', id='type-changed'),
        ],
    )
    def test_single_column_diff(
        self,
        schema_a: dict[str, str],
        schema_b: dict[str, str],
        column: str,
        status: str,
        type_a: str | None,
        type_b: str | None,
    ) -> None:
        diffs = _compute_schema_diff(schema_a, schema_b)
        assert len(diffs) == 1
        assert diffs[0].column == column
        assert diffs[0].status == status
        assert diffs[0].type_a == type_a
        assert diffs[0].type_b == type_b

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


class TestCompareComputeWorkerRuns:
    def test_compare_two_runs(self, test_db_session: Session) -> None:
        datasource_id = str(uuid.uuid4())
        run_a = create_compute_worker_run(
            test_db_session,
            datasource_id=datasource_id,
            result_json={'schema': {'col_a': 'Int64', 'col_b': 'Utf8'}, 'row_count': 100},
            step_timings={'filter': 50, 'select': 30},
            duration_ms=80,
        )
        run_b = create_compute_worker_run(
            test_db_session,
            datasource_id=datasource_id,
            result_json={'schema': {'col_a': 'Int64', 'col_c': 'Float64'}, 'row_count': 150},
            step_timings={'filter': 40, 'select': 35, 'sort': 10},
            duration_ms=85,
        )
        run_b.datasource_id = run_a.datasource_id
        test_db_session.add(run_b)
        test_db_session.commit()
        test_db_session.refresh(run_b)

        result = compare_compute_worker_runs(test_db_session, run_a.id, run_b.id)

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
        run_a = create_compute_worker_run(test_db_session, result_json={})
        missing_id = str(uuid.uuid4())
        with pytest.raises(AppError, match='not found') as exc_info:
            compare_compute_worker_runs(test_db_session, run_a.id, missing_id)
        assert exc_info.value.error_code == 'ENGINE_RUN_NOT_FOUND'

    def test_compare_requires_same_datasource(self, test_db_session: Session) -> None:
        run_a = create_compute_worker_run(test_db_session, result_json={'row_count': 1})
        run_b = create_compute_worker_run(test_db_session, result_json={'row_count': 2})
        with pytest.raises(ComputeWorkerRunComparisonError, match='same datasource'):
            compare_compute_worker_runs(test_db_session, run_a.id, run_b.id)

    def test_compare_runs_without_result_json(self, test_db_session: Session) -> None:
        datasource_id = str(uuid.uuid4())
        run_a = create_compute_worker_run(test_db_session, result_json=None, datasource_id=datasource_id)
        run_b = create_compute_worker_run(test_db_session, result_json=None, datasource_id=datasource_id)

        result = compare_compute_worker_runs(test_db_session, run_a.id, run_b.id)
        assert result.row_count_a is None
        assert result.row_count_b is None
        assert result.row_count_delta is None
        assert result.schema_diff == []
        assert result.timing_diff == []

    def test_compare_row_count_as_string(self, test_db_session: Session) -> None:
        """Row count stored as string (common from engine) should be parsed."""
        datasource_id = str(uuid.uuid4())
        run_a = create_compute_worker_run(test_db_session, result_json={'row_count': '200'}, datasource_id=datasource_id)
        run_b = create_compute_worker_run(test_db_session, result_json={'row_count': '300'}, datasource_id=datasource_id)

        result = compare_compute_worker_runs(test_db_session, run_a.id, run_b.id)
        assert result.row_count_a == 200
        assert result.row_count_b == 300
        assert result.row_count_delta == 100
