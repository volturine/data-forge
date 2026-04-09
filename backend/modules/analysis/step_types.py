from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Final


class ChartType(StrEnum):
    BAR = 'bar'
    HORIZONTAL_BAR = 'horizontal_bar'
    AREA = 'area'
    HEATGRID = 'heatgrid'
    HISTOGRAM = 'histogram'
    SCATTER = 'scatter'
    LINE = 'line'
    PIE = 'pie'
    BOXPLOT = 'boxplot'


@dataclass(frozen=True, slots=True)
class StepType:
    value: str
    label: str
    normalized: str | None = None
    chart_type: ChartType | None = None

    @property
    def canonical(self) -> str:
        return self.normalized or self.value

    @property
    def is_plot_alias(self) -> bool:
        return self.chart_type is not None


@dataclass(frozen=True, slots=True)
class StepTypes:
    select: StepType = StepType(value='select', label='Select')
    drop: StepType = StepType(value='drop', label='Drop')
    filter: StepType = StepType(value='filter', label='Filter')
    groupby: StepType = StepType(value='groupby', label='Group By')
    join: StepType = StepType(value='join', label='Join')
    union_by_name: StepType = StepType(value='union_by_name', label='Union By Name')
    unpivot: StepType = StepType(value='unpivot', label='Unpivot')
    explode: StepType = StepType(value='explode', label='Explode')
    pivot: StepType = StepType(value='pivot', label='Pivot')
    sample: StepType = StepType(value='sample', label='Sample')
    limit: StepType = StepType(value='limit', label='Limit')
    topk: StepType = StepType(value='topk', label='Top K')
    view: StepType = StepType(value='view', label='View')
    export: StepType = StepType(value='export', label='Export')
    download: StepType = StepType(value='download', label='Download')
    chart: StepType = StepType(value='chart', label='Chart')
    notification: StepType = StepType(value='notification', label='Notify')
    ai: StepType = StepType(value='ai', label='AI')
    datasource: StepType = StepType(value='datasource', label='Datasource')
    sort: StepType = StepType(value='sort', label='Sort')
    rename: StepType = StepType(value='rename', label='Rename')
    expression: StepType = StepType(value='expression', label='Expression')
    with_columns: StepType = StepType(value='with_columns', label='With Columns')
    fill_null: StepType = StepType(value='fill_null', label='Fill Null')
    deduplicate: StepType = StepType(value='deduplicate', label='Deduplicate')
    string_transform: StepType = StepType(value='string_transform', label='String Transform')
    timeseries: StepType = StepType(value='timeseries', label='Time Series')
    plot_bar: StepType = StepType(
        value='plot_bar',
        label='Bar Chart',
        normalized='chart',
        chart_type=ChartType.BAR,
    )
    plot_horizontal_bar: StepType = StepType(
        value='plot_horizontal_bar',
        label='Horizontal Bar Chart',
        normalized='chart',
        chart_type=ChartType.HORIZONTAL_BAR,
    )
    plot_area: StepType = StepType(
        value='plot_area',
        label='Area Chart',
        normalized='chart',
        chart_type=ChartType.AREA,
    )
    plot_heatgrid: StepType = StepType(
        value='plot_heatgrid',
        label='Heatgrid',
        normalized='chart',
        chart_type=ChartType.HEATGRID,
    )
    plot_histogram: StepType = StepType(
        value='plot_histogram',
        label='Histogram',
        normalized='chart',
        chart_type=ChartType.HISTOGRAM,
    )
    plot_scatter: StepType = StepType(
        value='plot_scatter',
        label='Scatter Plot',
        normalized='chart',
        chart_type=ChartType.SCATTER,
    )
    plot_line: StepType = StepType(
        value='plot_line',
        label='Line Chart',
        normalized='chart',
        chart_type=ChartType.LINE,
    )
    plot_pie: StepType = StepType(
        value='plot_pie',
        label='Pie Chart',
        normalized='chart',
        chart_type=ChartType.PIE,
    )
    plot_boxplot: StepType = StepType(
        value='plot_boxplot',
        label='Box Plot',
        normalized='chart',
        chart_type=ChartType.BOXPLOT,
    )

    def _definition_for(self, step_type: str) -> StepType | None:
        for step_field in fields(self):
            definition = getattr(self, step_field.name)
            if definition.value == step_type:
                return definition
        return None

    def all(self, *, include_plot_aliases: bool = True) -> tuple[str, ...]:
        step_types = tuple(getattr(self, step_field.name).value for step_field in fields(self))
        if include_plot_aliases:
            return step_types
        return tuple(step_type for step_type in step_types if not self.is_plot_alias(step_type))

    def has(self, step_type: str) -> bool:
        return self._definition_for(step_type) is not None

    def is_plot_alias(self, step_type: str) -> bool:
        definition = self._definition_for(step_type)
        return definition.is_plot_alias if definition is not None else False

    def is_chart_step_type(self, step_type: str) -> bool:
        return step_type == self.chart.value or self.is_plot_alias(step_type)

    def normalized(self, step_type: str) -> str:
        definition = self._definition_for(step_type)
        if definition is None:
            return step_type
        return definition.canonical

    def chart_type(self, step_type: str) -> ChartType | None:
        definition = self._definition_for(step_type)
        return definition.chart_type if definition is not None else None

    def label(self, step_type: str) -> str:
        definition = self._definition_for(step_type)
        if definition is not None:
            return definition.label
        return ' '.join(part.capitalize() for part in step_type.split('_') if part) or 'Unnamed Step'


STEP_TYPES: Final[StepTypes] = StepTypes()


def iter_step_types(*, include_plot_aliases: bool = True) -> tuple[str, ...]:
    return STEP_TYPES.all(include_plot_aliases=include_plot_aliases)


def is_plot_alias_step_type(step_type: str) -> bool:
    return STEP_TYPES.is_plot_alias(step_type)


def is_chart_step_type(step_type: str) -> bool:
    return STEP_TYPES.is_chart_step_type(step_type)


def is_step_type(step_type: str) -> bool:
    return STEP_TYPES.has(step_type)


def normalize_step_type(step_type: str) -> str:
    return STEP_TYPES.normalized(step_type)


def chart_type_for_step(step_type: str) -> ChartType | None:
    return STEP_TYPES.chart_type(step_type)


def get_step_type_label(step_type: str) -> str:
    return STEP_TYPES.label(step_type)
