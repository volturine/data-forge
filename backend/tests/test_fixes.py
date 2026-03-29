"""Tests for bug fixes and new features."""

import os
import tempfile
import uuid
from unittest.mock import patch

import polars as pl
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from modules.analysis.models import AnalysisDataSource
from modules.compute.engine import PolarsComputeEngine
from modules.compute.operations.notification import NotificationHandler, NotificationParams
from modules.compute.operations.plot import ChartHandler, ChartParams, compute_chart_data
from modules.datasource.models import DataSource
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
            'group_rank': ['b', 'a', 'b', 'a', 'b'],
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
        assert params.sort_by is None
        assert params.sort_order == 'asc'
        assert params.legend_position == 'right'
        assert params.decimal_places == 2
        assert params.stack_mode == 'grouped'
        assert params.group_sort_by is None
        assert params.group_sort_order == 'asc'

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'unknown': True,
                }
            )

    def test_group_sort_fields(self):
        params = ChartParams.model_validate(
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'group_column': 'group',
                'group_sort_by': 'value',
                'group_sort_order': 'desc',
            }
        )
        assert params.group_sort_by == 'value'
        assert params.group_sort_order == 'desc'

    def test_overlay_validation(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'overlays': [
                        {
                            'chart_type': 'line',
                            'y_column': 'value',
                            'aggregation': 'sum',
                            'y_axis_position': 'left',
                            'extra': True,
                        }
                    ],
                }
            )

    def test_reference_line_validation(self):
        with pytest.raises(ValidationError):
            ChartParams.model_validate(
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'reference_lines': [
                        {
                            'axis': 'z',
                            'value': 1,
                        }
                    ],
                }
            )

    def test_reference_line_value_optional(self):
        params = ChartParams.model_validate(
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'reference_lines': [
                    {
                        'axis': 'y',
                        'value': None,
                    }
                ],
            }
        )
        assert params.reference_lines[0].value is None

    def test_interactivity_defaults(self):
        params = ChartParams.model_validate(
            {
                'chart_type': 'bar',
                'x_column': 'category',
            }
        )
        assert params.pan_zoom_enabled is False
        assert params.selection_enabled is False
        assert params.area_selection_enabled is False


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

    def test_bar_aggregation_median(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'median',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == [15.0, 35.0, 50.0]

    def test_bar_aggregation_std(self):
        lf = pl.DataFrame(
            {
                'category': ['A', 'A', 'A', 'B', 'B', 'B'],
                'value': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'std',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == pytest.approx([1.0, 1.0])

    def test_bar_aggregation_variance(self):
        lf = pl.DataFrame(
            {
                'category': ['A', 'A', 'A', 'B', 'B', 'B'],
                'value': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'value',
                    'aggregation': 'variance',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == pytest.approx([1.0, 1.0])

    def test_bar_aggregation_unique_count(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'bar',
                    'x_column': 'category',
                    'y_column': 'group',
                    'aggregation': 'unique_count',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == [2, 2, 1]

    def test_bar_sort_by_y_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
                'sort_by': 'y',
                'sort_order': 'desc',
            },
        ).collect()

        assert result['y'].to_list() == sorted(result['y'].to_list(), reverse=True)

    def test_bar_sort_by_x_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
                'sort_by': 'x',
                'sort_order': 'desc',
            },
        ).collect()

        assert result['x'].to_list() == ['C', 'B', 'A']

    def test_bar_date_bucket_month(self):
        lf = pl.DataFrame(
            {
                'date': [
                    '2024-01-05T00:00:00',
                    '2024-01-15T00:00:00',
                    '2024-02-01T00:00:00',
                ],
                'value': [1, 2, 3],
            }
        ).lazy()
        result = (
            compute_chart_data(
                lf,
                {
                    'chart_type': 'bar',
                    'x_column': 'date',
                    'y_column': 'value',
                    'aggregation': 'sum',
                    'date_bucket': 'month',
                },
            )
            .collect()
            .sort('x')
        )

        assert result['y'].to_list() == [3, 3]

    def test_bar_group_sort_by_value_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
                'group_column': 'group',
                'group_sort_by': 'value',
                'group_sort_order': 'desc',
            },
        ).collect()

        groups = result['group'].to_list()
        assert groups[:2] == ['y', 'y']

    def test_bar_group_sort_by_name_desc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
                'group_column': 'group',
                'group_sort_by': 'name',
                'group_sort_order': 'desc',
            },
        ).collect()

        groups = result['group'].to_list()
        assert groups[:2] == ['y', 'y']

    def test_bar_group_sort_by_custom_asc(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'bar',
                'x_column': 'category',
                'y_column': 'value',
                'aggregation': 'sum',
                'group_column': 'group',
                'group_sort_by': 'custom',
                'group_sort_order': 'asc',
                'group_sort_column': 'group_rank',
            },
        ).collect()

        groups = result['group'].to_list()
        assert groups[:2] == ['y', 'y']


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

    def test_pie_sort_by_label(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'pie',
                'x_column': 'category',
                'y_column': 'value',
                'sort_by': 'x',
                'sort_order': 'asc',
            },
        ).collect()

        assert result['label'].to_list() == ['A', 'B', 'C']

    def test_pie_group_sort_by_name(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'pie',
                'x_column': 'category',
                'y_column': 'value',
                'group_column': 'group',
                'group_sort_by': 'name',
                'group_sort_order': 'desc',
            },
        ).collect()

        assert result['group'].to_list()[0] == 'y'

    def test_pie_date_ordinal_day_of_week(self):
        lf = pl.DataFrame(
            {
                'date': [
                    '2024-01-01T00:00:00',
                    '2024-01-08T00:00:00',
                ],
                'value': [5, 7],
            }
        ).lazy()
        result = compute_chart_data(
            lf,
            {
                'chart_type': 'pie',
                'x_column': 'date',
                'y_column': 'value',
                'date_ordinal': 'day_of_week',
            },
        ).collect()

        assert set(result['label'].to_list()) == {0}

    def test_pie_group_sort_by_value(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'pie',
                'x_column': 'category',
                'y_column': 'value',
                'group_column': 'group',
                'group_sort_by': 'value',
                'group_sort_order': 'desc',
            },
        ).collect()

        assert result['group'].to_list()[0] == 'y'

    def test_pie_group_sort_by_custom(self):
        result = compute_chart_data(
            _chart_frame(),
            {
                'chart_type': 'pie',
                'x_column': 'category',
                'y_column': 'value',
                'group_column': 'group',
                'group_sort_by': 'custom',
                'group_sort_order': 'desc',
                'group_sort_column': 'group',
            },
        ).collect()

        assert result['group'].to_list()[0] == 'y'


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


class TestChartDataHeatgrid:
    def test_heatgrid_basic(self):
        result = (
            compute_chart_data(
                _chart_frame(),
                {
                    'chart_type': 'heatgrid',
                    'x_column': 'category',
                    'y_column': 'group',
                    'aggregation': 'count',
                },
            )
            .collect()
            .sort(['x', 'y'])
        )

        assert result.columns == ['x', 'y', 'value']
        assert result['value'].to_list() == [1, 1, 1, 1, 1]


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


# ---------------------------------------------------------------------------
# ChartParams sort_by / group_sort_by coercion
# ---------------------------------------------------------------------------


class TestChartParamsSortByCoercion:
    def test_invalid_sort_by_coerces_to_none(self):
        params = ChartParams.model_validate({'chart_type': 'bar', 'x_column': 'cat', 'sort_by': 'rank'})
        assert params.sort_by is None

    def test_invalid_group_sort_by_coerces_to_none(self):
        params = ChartParams.model_validate({'chart_type': 'bar', 'x_column': 'cat', 'group_sort_by': 'total'})
        assert params.group_sort_by is None

    def test_valid_sort_by_preserved(self):
        params = ChartParams.model_validate({'chart_type': 'bar', 'x_column': 'cat', 'sort_by': 'y'})
        assert params.sort_by == 'y'

    def test_valid_group_sort_by_preserved(self):
        params = ChartParams.model_validate({'chart_type': 'bar', 'x_column': 'cat', 'group_sort_by': 'value'})
        assert params.group_sort_by == 'value'

    def test_invalid_sort_by_does_not_raise_in_compute(self):
        lf = pl.DataFrame({'cat': ['A', 'B'], 'val': [1.0, 2.0]}).lazy()
        result = compute_chart_data(lf, {'chart_type': 'bar', 'x_column': 'cat', 'y_column': 'val', 'sort_by': 'rank'}).collect()
        assert result.height == 2


# ---------------------------------------------------------------------------
# Analysis datasource deduplication on create
# ---------------------------------------------------------------------------


class TestAnalysisDatasourceDedupe:
    def test_duplicate_datasource_across_tabs_inserts_one_row(self, client, sample_datasource: DataSource, test_db_session):
        shared_id = sample_datasource.id
        payload = {
            'name': 'Dedup Test',
            'description': '',
            'tabs': [
                {
                    'id': 'tab1',
                    'name': 'Tab 1',
                    'parent_id': None,
                    'datasource': {'id': shared_id, 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                    'output': {'result_id': str(uuid.uuid4()), 'format': 'parquet', 'filename': 'out1'},
                    'steps': [],
                },
                {
                    'id': 'tab2',
                    'name': 'Tab 2',
                    'parent_id': None,
                    'datasource': {'id': shared_id, 'analysis_tab_id': None, 'config': {'branch': 'master'}},
                    'output': {'result_id': str(uuid.uuid4()), 'format': 'parquet', 'filename': 'out2'},
                    'steps': [],
                },
            ],
        }
        response = client.post('/api/v1/analysis', json=payload)
        assert response.status_code == 200
        analysis_id = response.json()['id']
        rows = test_db_session.execute(select(AnalysisDataSource).where(AnalysisDataSource.analysis_id == analysis_id)).scalars().all()
        assert len(rows) == 1
        assert rows[0].datasource_id == shared_id


# ---------------------------------------------------------------------------
# Security audit fixes — PR #30
# ---------------------------------------------------------------------------


class TestSafeBuiltinsUdf:
    """UDF execution sandbox must not allow attribute-chain escapes."""

    def _run_udf(self, code: str):
        # exec() here is intentional: we are verifying that the _SAFE_BUILTINS
        # sandbox correctly blocks dangerous builtins. The code strings are
        # hard-coded in each test — no user input reaches this helper.
        from typing import Any
        from modules.compute.operations.with_columns import _SAFE_BUILTINS
        import polars as pl

        scope: dict[str, Any] = {'pl': pl, '__builtins__': _SAFE_BUILTINS}
        local_scope: dict[str, Any] = {}
        exec(code, scope, local_scope)  # noqa: S102
        udf = local_scope.get('udf') or scope.get('udf')
        return udf() if udf else None

    def test_getattr_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf(): return getattr([], "__class__")')

    def test_setattr_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf():\n    class C: pass\n    setattr(C, "x", 1)\n    return C.x')

    def test_vars_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf(): return vars()')

    def test_dir_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf(): return dir([])')

    def test_open_blocked(self):
        with pytest.raises((NameError, TypeError)):
            self._run_udf('def udf(): return open("/etc/passwd")')

    def test_safe_arithmetic_works(self):
        result = self._run_udf('def udf(): return 2 + 2')
        assert result == 4

    def test_safe_len_works(self):
        result = self._run_udf('def udf(): return len([1, 2, 3])')
        assert result == 3


class TestValidateRegexPattern:
    """Shared _validation.validate_regex_pattern helper."""

    def test_valid_pattern_passes(self):
        from modules.compute.operations._validation import validate_regex_pattern

        validate_regex_pattern(r'\d+')

    def test_invalid_pattern_raises(self):
        from modules.compute.operations._validation import validate_regex_pattern

        with pytest.raises(ValueError, match='Invalid regex pattern'):
            validate_regex_pattern(r'[unclosed')


class TestAssertSelectOnly:
    """SQL read-only guard in datasource operations."""

    def _check(self, query: str):
        from modules.compute.operations.datasource import _assert_select_only

        _assert_select_only(query)

    def test_select_allowed(self):
        self._check('SELECT * FROM t')

    def test_select_leading_whitespace(self):
        self._check('  SELECT * FROM t')

    def test_with_cte_allowed(self):
        self._check('WITH cte AS (SELECT 1) SELECT * FROM cte')

    def test_insert_rejected(self):
        with pytest.raises(ValueError, match='Only SELECT'):
            self._check('INSERT INTO t VALUES (1)')

    def test_drop_rejected(self):
        with pytest.raises(ValueError, match='Only SELECT'):
            self._check('DROP TABLE t')

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match='Only SELECT'):
            self._check('')


class TestParseDatetimeString:
    """_parse_datetime_string fallback format coverage."""

    def test_iso8601(self):
        from modules.compute.operations.filter import _parse_datetime_string
        from datetime import datetime

        dt = _parse_datetime_string('2024-06-15T12:30:00')
        assert dt == datetime(2024, 6, 15, 12, 30, 0)

    def test_z_suffix(self):
        from modules.compute.operations.filter import _parse_datetime_string

        dt = _parse_datetime_string('2024-06-15T12:30:00Z')
        assert dt.year == 2024 and dt.month == 6 and dt.day == 15

    def test_space_separated(self):
        from modules.compute.operations.filter import _parse_datetime_string
        from datetime import datetime

        dt = _parse_datetime_string('2024-06-15 12:30:00')
        assert dt == datetime(2024, 6, 15, 12, 30, 0)

    def test_invalid_raises(self):
        from modules.compute.operations.filter import _parse_datetime_string

        with pytest.raises(ValueError, match='Cannot parse datetime string'):
            _parse_datetime_string('not-a-date')


class TestCoerceValueNumber:
    """coerce_value handles scientific notation strings correctly."""

    def test_integer_string(self):
        from modules.compute.operations.filter import coerce_value

        assert coerce_value('42', 'number') == 42
        assert isinstance(coerce_value('42', 'number'), int)

    def test_float_string(self):
        from modules.compute.operations.filter import coerce_value

        assert coerce_value('3.14', 'number') == pytest.approx(3.14)

    def test_scientific_notation(self):
        from modules.compute.operations.filter import coerce_value

        val = coerce_value('1e5', 'number')
        assert val == pytest.approx(100000.0)
        assert isinstance(val, float)  # '1e5' contains 'e', must stay float
