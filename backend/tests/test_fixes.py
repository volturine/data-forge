"""Tests for bug fixes and new features."""

import os
import tempfile
from unittest.mock import patch

import polars as pl
import pytest
from pydantic import ValidationError

from modules.compute.engine import PolarsComputeEngine
from modules.compute.operations.notification import NotificationHandler, NotificationParams
from modules.compute.operations.plot import ChartHandler, ChartParams, compute_chart_data
from modules.engine_runs.schemas import EngineRunResponseSchema

# ---------------------------------------------------------------------------
# EngineRunResponseSchema.progress default
# ---------------------------------------------------------------------------


class TestEngineRunProgressDefault:
    def test_progress_defaults_to_zero(self):
        """progress: float = 0.0 means NULL from DB should not crash."""
        data = {
            'id': 'run-1',
            'analysis_id': None,
            'datasource_id': 'ds-1',
            'kind': 'preview',
            'status': 'success',
            'request_json': {},
            'result_json': None,
            'error_message': None,
            'created_at': '2024-01-01T00:00:00',
            'completed_at': None,
            'duration_ms': None,
            'step_timings': {},
            'query_plan': None,
            'current_step': None,
        }
        schema = EngineRunResponseSchema.model_validate(data)
        assert schema.progress == 0.0

    def test_progress_explicit_value(self):
        data = {
            'id': 'run-2',
            'analysis_id': None,
            'datasource_id': 'ds-1',
            'kind': 'preview',
            'status': 'running',
            'request_json': {},
            'result_json': None,
            'error_message': None,
            'created_at': '2024-01-01T00:00:00',
            'completed_at': None,
            'duration_ms': None,
            'step_timings': {},
            'query_plan': None,
            'progress': 0.75,
            'current_step': 'filter',
        }
        schema = EngineRunResponseSchema.model_validate(data)
        assert schema.progress == 0.75


# ---------------------------------------------------------------------------
# NotificationHandler
# ---------------------------------------------------------------------------


class TestNotificationHandler:
    def test_per_row_sends_and_adds_status_column(self):
        """NotificationHandler sends per-row and adds output status column."""
        handler = NotificationHandler()
        lf = pl.DataFrame({'msg': ['hello', 'world']}).lazy()
        with patch('modules.compute.operations.notification.notification_service') as mock_svc:
            result = handler(
                lf,
                {
                    'method': 'email',
                    'recipient': 'test@example.com',
                    'input_columns': ['msg'],
                    'output_column': 'status',
                    'message_template': '{{msg}}',
                    'subject_template': 'Test',
                },
            )
            collected = result.collect()
        assert 'status' in collected.columns
        assert collected['status'].to_list() == ['sent', 'sent']
        assert mock_svc.send_email.call_count == 2

    def test_validates_params(self):
        """Invalid params raise ValidationError."""
        handler = NotificationHandler()
        lf = pl.DataFrame({'a': [1]}).lazy()
        with pytest.raises(ValidationError):
            handler(lf, {'method': 'invalid_method', 'recipient': 'test@test.com', 'input_columns': ['a']})

    def test_extra_fields_forbidden(self):
        """Extra fields in notification params are rejected."""
        with pytest.raises(ValidationError):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'recipient': 'test@test.com',
                    'input_columns': ['a'],
                    'unknown_field': 'bad',
                }
            )

    def test_defaults(self):
        """Default values are applied correctly."""
        params = NotificationParams.model_validate(
            {
                'method': 'email',
                'recipient': 'test@test.com',
                'input_columns': ['col'],
            }
        )
        assert params.subject_template == 'Notification'
        assert params.output_column == 'notification_status'
        assert params.message_template == '{{message}}'
        assert params.batch_size == 10
        assert params.timeout_seconds == 20


# render_template and _send_pipeline_notifications tests moved to test_notification.py


# ---------------------------------------------------------------------------
# ChartHandler
# ---------------------------------------------------------------------------


def _chart_frame() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            'category': ['A', 'A', 'B', 'B', 'C'],
            'value': [10.0, 20.0, 30.0, 40.0, 50.0],
            'group': ['x', 'y', 'x', 'y', 'x'],
        }
    ).lazy()


class TestChartParams:
    def test_defaults(self):
        params = ChartParams.model_validate(
            {
                'chart_type': 'bar',
                'x_column': 'category',
            }
        )
        assert params.aggregation == 'sum'
        assert params.bins == 10
        assert params.y_column is None
        assert params.group_column is None

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'unknown': True,
                }
            )


class TestChartHandlerPassThrough:
    """Chart handler must return input lf unchanged (pass-through for DAG)."""

    def test_pass_through_preserves_schema(self):
        handler = ChartHandler()
        lf = _chart_frame()
        result = handler(
            lf,
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
            },
        )
        # Pass-through: output columns must match input columns
        assert result.collect_schema().names() == lf.collect_schema().names()

    def test_pass_through_data_unchanged(self):
        handler = ChartHandler()
        lf = _chart_frame()
        result = handler(lf, {'chart_type': 'scatter', 'x_column': 'category', 'y_column': 'value'})
        assert result.collect().height == lf.collect().height
        assert result.collect().columns == lf.collect().columns


class TestChartDataBar:
    def test_bar_no_group(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'sum',
                },
            )
            .collect()
            .sort('x')
        )

        assert result.columns == ['x', 'y']
        assert result['x'].to_list() == ['A', 'B', 'C']
        assert result['y'].to_list() == [30.0, 70.0, 50.0]

    def test_bar_with_group(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'sum',
                    'group_column': 'group',
                },
            )
            .collect()
            .sort('x', 'group')
        )

        assert 'group' in result.columns
        assert result.height == 5  # A-x, A-y, B-x, B-y, C-x

    def test_bar_count_no_y(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == [2, 2, 1]

    def test_bar_aggregation_mean(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'mean',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == [15.0, 35.0, 50.0]


class TestChartDataLine:
    def test_line_basic(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'line',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'sum',
                },
            )
            .collect()
            .sort('x')
        )

        assert result.columns == ['x', 'y']
        assert result['x'].to_list() == ['A', 'B', 'C']

    def test_line_with_group(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'line',
                'x_column': 'category',
                'y_column': 'value',
                'group_column': 'group',
            },
        ).collect()

        assert 'group' in result.columns


class TestChartDataPie:
    def test_pie_basic(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'pie',
                'x_column': 'category',
                'y_column': 'value',
            },
        ).collect()

        assert 'label' in result.columns
        assert 'y' in result.columns
        assert set(result['label'].to_list()) == {'A', 'B', 'C'}

    def test_pie_sorted_descending(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'pie',
                'x_column': 'category',
                'y_column': 'value',
            },
        ).collect()

        # Should be sorted by y descending
        values = result['y'].to_list()
        assert values == sorted(values, reverse=True)


class TestChartDataHistogram:
    def test_histogram_basic(self):
        lf = pl.DataFrame({'val': list(range(100))}).lazy()
        result = compute_chart_data(
            lf,
            {
                'chart_type': 'histogram',
                'x_column': 'val',
                'bins': 10,
            },
        ).collect()

        assert result.columns == ['bin_start', 'bin_end', 'count']
        assert result.height == 10
        assert sum(result['count'].to_list()) == 100

    def test_histogram_empty(self):
        lf = pl.DataFrame({'val': []}).cast({'val': pl.Float64}).lazy()
        result = compute_chart_data(
            lf,
            {
                'chart_type': 'histogram',
                'x_column': 'val',
            },
        ).collect()

        assert result.height == 0

    def test_histogram_single_value(self):
        lf = pl.DataFrame({'val': [5.0, 5.0, 5.0]}).lazy()
        result = compute_chart_data(
            lf,
            {
                'chart_type': 'histogram',
                'x_column': 'val',
            },
        ).collect()

        assert result.height == 1
        assert result['count'].to_list() == [3]


class TestChartDataScatter:
    def test_scatter_basic(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'scatter',
                'x_column': 'category',
                'y_column': 'value',
            },
        ).collect()

        assert 'x' in result.columns
        assert 'y' in result.columns
        assert result.height == 5

    def test_scatter_with_group(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'scatter',
                'x_column': 'category',
                'y_column': 'value',
                'group_column': 'group',
            },
        ).collect()

        assert 'group' in result.columns

    def test_scatter_limit_5000(self):
        lf = pl.DataFrame(
            {
                'x': list(range(10000)),
                'y': list(range(10000)),
            }
        ).lazy()
        result = compute_chart_data(
            lf,
            {
                'chart_type': 'scatter',
                'x_column': 'x',
                'y_column': 'y',
            },
        ).collect()

        assert result.height == 5000


class TestChartDataBoxplot:
    def test_boxplot_with_group(self):
        lf = pl.DataFrame(
            {
                'cat': ['A'] * 100 + ['B'] * 100,
                'val': list(range(100)) + list(range(50, 150)),
            }
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    'chart_type': 'boxplot',
                    'x_column': 'cat',
                    'y_column': 'val',
                },
            )
            .collect()
            .sort('group')
        )

        assert result.columns == ['group', 'min', 'q1', 'median', 'q3', 'max']
        assert result.height == 2
        assert result['group'].to_list() == ['A', 'B']
        # A: min=0, max=99; B: min=50, max=149
        assert result['min'].to_list() == [0.0, 50.0]
        assert result['max'].to_list() == [99.0, 149.0]

    def test_boxplot_no_group(self):
        lf = pl.DataFrame({'val': list(range(100))}).lazy()
        result = compute_chart_data(
            lf,
            {
                'chart_type': 'boxplot',
                'x_column': 'val',
            },
        ).collect()

        assert result.height == 1
        assert 'group' in result.columns
        assert result['group'].to_list() == ['all']
        assert result['min'][0] == 0.0
        assert result['max'][0] == 99.0


# ---------------------------------------------------------------------------
# Step Timing Labels — human-readable names instead of UUIDs
# ---------------------------------------------------------------------------


class TestStepTimingLabels:
    def _make_csv_config(self) -> tuple[str, dict]:
        """Create a temp CSV file and return (path, datasource_config)."""
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w') as f:
            f.write('a,b\n1,4\n2,5\n3,6\n')
        config = {'source_type': 'file', 'file_path': path, 'file_type': 'csv'}
        return path, config

    def test_timing_keys_use_step_type(self):
        """step_timings keys should use step type, not UUID."""
        path, config = self._make_csv_config()
        try:
            steps = [
                {'id': 'id-abc123', 'type': 'select', 'config': {'columns': ['a']}, 'depends_on': []},
            ]
            _, timings, _plan_frames = PolarsComputeEngine._build_pipeline(config, steps, 'job-1')
            assert 'select' in timings
            assert 'id-abc123' not in timings
        finally:
            os.unlink(path)

    def test_timing_keys_deduplicate(self):
        """Multiple steps of same type get _2, _3, etc."""
        path, config = self._make_csv_config()
        try:
            steps = [
                {'id': 'id-1', 'type': 'select', 'config': {'columns': ['a', 'b']}, 'depends_on': []},
                {'id': 'id-2', 'type': 'select', 'config': {'columns': ['a']}, 'depends_on': ['id-1']},
            ]
            _, timings, _plan_frames = PolarsComputeEngine._build_pipeline(config, steps, 'job-2')
            assert 'select' in timings
            assert 'select_2' in timings
        finally:
            os.unlink(path)
