"""Tests for bug fixes and new features."""

import polars as pl
import pytest
from pydantic import ValidationError

from modules.compute.operations.notification import NotificationHandler, NotificationParams
from modules.compute.operations.plot import ChartHandler, ChartParams
from modules.engine_runs.schemas import EngineRunResponseSchema
from modules.notification.service import render_template

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
    def test_pass_through(self):
        """NotificationHandler validates config and returns LazyFrame unchanged."""
        handler = NotificationHandler()
        lf = pl.DataFrame({'a': [1, 2]}).lazy()
        result = handler(
            lf,
            {
                'method': 'email',
                'recipient': 'test@example.com',
            },
        )
        assert result.collect().equals(lf.collect())

    def test_validates_params(self):
        """Invalid params raise ValidationError."""
        handler = NotificationHandler()
        lf = pl.DataFrame({'a': [1]}).lazy()
        with pytest.raises(ValidationError):
            handler(lf, {'method': 'invalid_method', 'recipient': 'test@test.com'})

    def test_extra_fields_forbidden(self):
        """Extra fields in notification params are rejected."""
        with pytest.raises(ValidationError):
            NotificationParams.model_validate(
                {
                    'method': 'email',
                    'recipient': 'test@test.com',
                    'unknown_field': 'bad',
                }
            )

    def test_defaults(self):
        """Default values are applied correctly."""
        params = NotificationParams.model_validate(
            {
                'method': 'email',
                'recipient': 'test@test.com',
            }
        )
        assert params.subject_template == 'Build Complete: {{analysis_name}}'
        assert params.attach_result is False
        assert params.attach_error is True
        assert params.timeout_seconds == 20
        assert params.retries == 0


# ---------------------------------------------------------------------------
# render_template
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_basic(self):
        result = render_template('Hello {{name}}!', {'name': 'World'})
        assert result == 'Hello World!'

    def test_multiple(self):
        result = render_template(
            '{{a}} and {{b}}',
            {'a': 'foo', 'b': 'bar'},
        )
        assert result == 'foo and bar'

    def test_missing_key(self):
        result = render_template('Hello {{name}}!', {})
        assert result == 'Hello {{name}}!'

    def test_numeric_value(self):
        result = render_template('Count: {{count}}', {'count': 42})
        assert result == 'Count: 42'


# ---------------------------------------------------------------------------
# _send_pipeline_notifications
# ---------------------------------------------------------------------------


class TestSendPipelineNotifications:
    def test_skips_non_notification_steps(self):
        """Non-notification steps are ignored."""
        from modules.compute.service import _send_pipeline_notifications

        # Should not raise even with no notification service configured
        _send_pipeline_notifications(
            pipeline_steps=[
                {'type': 'filter', 'config': {}},
                {'type': 'export', 'config': {}},
            ],
            context={'status': 'success'},
        )

    def test_skips_empty_recipient(self):
        """Notification steps with empty recipient are skipped."""
        from modules.compute.service import _send_pipeline_notifications

        _send_pipeline_notifications(
            pipeline_steps=[
                {'type': 'notification', 'config': {'method': 'email', 'recipient': ''}},
            ],
            context={'status': 'success'},
        )


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


class TestChartHandlerBar:
    def test_bar_no_group(self):
        handler = ChartHandler()
        result = (
            handler(
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
        handler = ChartHandler()
        result = (
            handler(
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
        handler = ChartHandler()
        result = (
            handler(
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
        handler = ChartHandler()
        result = (
            handler(
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


class TestChartHandlerLine:
    def test_line_basic(self):
        handler = ChartHandler()
        result = (
            handler(
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
        handler = ChartHandler()
        result = handler(
            _chart_frame(),
            {
                'chart_type': 'line',
                'x_column': 'category',
                'y_column': 'value',
                'group_column': 'group',
            },
        ).collect()

        assert 'group' in result.columns


class TestChartHandlerPie:
    def test_pie_basic(self):
        handler = ChartHandler()
        result = handler(
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
        handler = ChartHandler()
        result = handler(
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


class TestChartHandlerHistogram:
    def test_histogram_basic(self):
        handler = ChartHandler()
        lf = pl.DataFrame({'val': list(range(100))}).lazy()
        result = handler(
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
        handler = ChartHandler()
        lf = pl.DataFrame({'val': []}).cast({'val': pl.Float64}).lazy()
        result = handler(
            lf,
            {
                'chart_type': 'histogram',
                'x_column': 'val',
            },
        ).collect()

        assert result.height == 0

    def test_histogram_single_value(self):
        handler = ChartHandler()
        lf = pl.DataFrame({'val': [5.0, 5.0, 5.0]}).lazy()
        result = handler(
            lf,
            {
                'chart_type': 'histogram',
                'x_column': 'val',
            },
        ).collect()

        assert result.height == 1
        assert result['count'].to_list() == [3]


class TestChartHandlerScatter:
    def test_scatter_basic(self):
        handler = ChartHandler()
        result = handler(
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
        handler = ChartHandler()
        result = handler(
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
        handler = ChartHandler()
        lf = pl.DataFrame(
            {
                'x': list(range(10000)),
                'y': list(range(10000)),
            }
        ).lazy()
        result = handler(
            lf,
            {
                'chart_type': 'scatter',
                'x_column': 'x',
                'y_column': 'y',
            },
        ).collect()

        assert result.height == 5000


class TestChartHandlerBoxplot:
    def test_boxplot_with_group(self):
        handler = ChartHandler()
        lf = pl.DataFrame(
            {
                'cat': ['A'] * 100 + ['B'] * 100,
                'val': list(range(100)) + list(range(50, 150)),
            }
        ).lazy()
        result = (
            handler(
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
        handler = ChartHandler()
        lf = pl.DataFrame({'val': list(range(100))}).lazy()
        result = handler(
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
