from backend_core.domain.analysis.step_types import (
    STEP_TYPES,
    PipelineStepType,
)
from dataforge_protocol import enums_pb2


def test_step_types_are_generated_protocol_backed() -> None:
    assert PipelineStepType.FILTER.number == enums_pb2.STEP_TYPE_FILTER
    assert PipelineStepType.require(enums_pb2.STEP_TYPE_FILTER) is PipelineStepType.FILTER
    assert PipelineStepType.require('filter') is PipelineStepType.FILTER
    assert PipelineStepType.FILTER == 'filter'
    assert hash(PipelineStepType.FILTER) == hash('filter')


def test_chart_alias_helpers_are_explicit() -> None:
    assert STEP_TYPES.is_plot_alias('plot_scatter')
    assert not STEP_TYPES.is_plot_alias('chart')
    assert STEP_TYPES.chart_type('plot_scatter') == 'scatter'
    assert STEP_TYPES.chart_type('chart') is None


def test_chart_step_normalization() -> None:
    assert STEP_TYPES.normalized('plot_bar') == 'chart'
    assert STEP_TYPES.normalized('filter') == 'filter'
