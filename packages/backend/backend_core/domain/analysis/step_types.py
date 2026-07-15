from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import ClassVar, Final, Self

from backend_core.domain.api_enums import ApiEnumValue, api_token
from dataforge_protocol import enums_pb2


class ChartType(ApiEnumValue):
    BAR: ClassVar[Self]
    HORIZONTAL_BAR: ClassVar[Self]
    AREA: ClassVar[Self]
    HEATGRID: ClassVar[Self]
    HISTOGRAM: ClassVar[Self]
    SCATTER: ClassVar[Self]
    LINE: ClassVar[Self]
    PIE: ClassVar[Self]
    BOXPLOT: ClassVar[Self]


ChartType.BAR = ChartType(enums_pb2.CHART_TYPE_BAR, api_token('ChartType', enums_pb2.CHART_TYPE_BAR))
ChartType.HORIZONTAL_BAR = ChartType(enums_pb2.CHART_TYPE_HORIZONTAL_BAR, api_token('ChartType', enums_pb2.CHART_TYPE_HORIZONTAL_BAR))
ChartType.AREA = ChartType(enums_pb2.CHART_TYPE_AREA, api_token('ChartType', enums_pb2.CHART_TYPE_AREA))
ChartType.HEATGRID = ChartType(enums_pb2.CHART_TYPE_HEATGRID, api_token('ChartType', enums_pb2.CHART_TYPE_HEATGRID))
ChartType.HISTOGRAM = ChartType(enums_pb2.CHART_TYPE_HISTOGRAM, api_token('ChartType', enums_pb2.CHART_TYPE_HISTOGRAM))
ChartType.SCATTER = ChartType(enums_pb2.CHART_TYPE_SCATTER, api_token('ChartType', enums_pb2.CHART_TYPE_SCATTER))
ChartType.LINE = ChartType(enums_pb2.CHART_TYPE_LINE, api_token('ChartType', enums_pb2.CHART_TYPE_LINE))
ChartType.PIE = ChartType(enums_pb2.CHART_TYPE_PIE, api_token('ChartType', enums_pb2.CHART_TYPE_PIE))
ChartType.BOXPLOT = ChartType(enums_pb2.CHART_TYPE_BOXPLOT, api_token('ChartType', enums_pb2.CHART_TYPE_BOXPLOT))


class PipelineStepType(ApiEnumValue):
    SELECT: ClassVar[Self]
    DROP: ClassVar[Self]
    FILTER: ClassVar[Self]
    GROUPBY: ClassVar[Self]
    JOIN: ClassVar[Self]
    UNION_BY_NAME: ClassVar[Self]
    UNPIVOT: ClassVar[Self]
    EXPLODE: ClassVar[Self]
    PIVOT: ClassVar[Self]
    SAMPLE: ClassVar[Self]
    LIMIT: ClassVar[Self]
    TOPK: ClassVar[Self]
    VIEW: ClassVar[Self]
    EXPORT: ClassVar[Self]
    DOWNLOAD: ClassVar[Self]
    CHART: ClassVar[Self]
    NOTIFICATION: ClassVar[Self]
    AI: ClassVar[Self]
    DATASOURCE: ClassVar[Self]
    SORT: ClassVar[Self]
    RENAME: ClassVar[Self]
    EXPRESSION: ClassVar[Self]
    WITH_COLUMNS: ClassVar[Self]
    FILL_NULL: ClassVar[Self]
    DEDUPLICATE: ClassVar[Self]
    STRING_TRANSFORM: ClassVar[Self]
    TIMESERIES: ClassVar[Self]
    PLOT_BAR: ClassVar[Self]
    PLOT_HORIZONTAL_BAR: ClassVar[Self]
    PLOT_AREA: ClassVar[Self]
    PLOT_HEATGRID: ClassVar[Self]
    PLOT_HISTOGRAM: ClassVar[Self]
    PLOT_SCATTER: ClassVar[Self]
    PLOT_LINE: ClassVar[Self]
    PLOT_PIE: ClassVar[Self]
    PLOT_BOXPLOT: ClassVar[Self]


PipelineStepType.SELECT = PipelineStepType(enums_pb2.STEP_TYPE_SELECT, api_token('StepType', enums_pb2.STEP_TYPE_SELECT))
PipelineStepType.DROP = PipelineStepType(enums_pb2.STEP_TYPE_DROP, api_token('StepType', enums_pb2.STEP_TYPE_DROP))
PipelineStepType.FILTER = PipelineStepType(enums_pb2.STEP_TYPE_FILTER, api_token('StepType', enums_pb2.STEP_TYPE_FILTER))
PipelineStepType.GROUPBY = PipelineStepType(enums_pb2.STEP_TYPE_GROUPBY, api_token('StepType', enums_pb2.STEP_TYPE_GROUPBY))
PipelineStepType.JOIN = PipelineStepType(enums_pb2.STEP_TYPE_JOIN, api_token('StepType', enums_pb2.STEP_TYPE_JOIN))
PipelineStepType.UNION_BY_NAME = PipelineStepType(enums_pb2.STEP_TYPE_UNION_BY_NAME, api_token('StepType', enums_pb2.STEP_TYPE_UNION_BY_NAME))
PipelineStepType.UNPIVOT = PipelineStepType(enums_pb2.STEP_TYPE_UNPIVOT, api_token('StepType', enums_pb2.STEP_TYPE_UNPIVOT))
PipelineStepType.EXPLODE = PipelineStepType(enums_pb2.STEP_TYPE_EXPLODE, api_token('StepType', enums_pb2.STEP_TYPE_EXPLODE))
PipelineStepType.PIVOT = PipelineStepType(enums_pb2.STEP_TYPE_PIVOT, api_token('StepType', enums_pb2.STEP_TYPE_PIVOT))
PipelineStepType.SAMPLE = PipelineStepType(enums_pb2.STEP_TYPE_SAMPLE, api_token('StepType', enums_pb2.STEP_TYPE_SAMPLE))
PipelineStepType.LIMIT = PipelineStepType(enums_pb2.STEP_TYPE_LIMIT, api_token('StepType', enums_pb2.STEP_TYPE_LIMIT))
PipelineStepType.TOPK = PipelineStepType(enums_pb2.STEP_TYPE_TOPK, api_token('StepType', enums_pb2.STEP_TYPE_TOPK))
PipelineStepType.VIEW = PipelineStepType(enums_pb2.STEP_TYPE_VIEW, api_token('StepType', enums_pb2.STEP_TYPE_VIEW))
PipelineStepType.EXPORT = PipelineStepType(enums_pb2.STEP_TYPE_EXPORT, api_token('StepType', enums_pb2.STEP_TYPE_EXPORT))
PipelineStepType.DOWNLOAD = PipelineStepType(enums_pb2.STEP_TYPE_DOWNLOAD, api_token('StepType', enums_pb2.STEP_TYPE_DOWNLOAD))
PipelineStepType.CHART = PipelineStepType(enums_pb2.STEP_TYPE_CHART, api_token('StepType', enums_pb2.STEP_TYPE_CHART))
PipelineStepType.NOTIFICATION = PipelineStepType(enums_pb2.STEP_TYPE_NOTIFICATION, api_token('StepType', enums_pb2.STEP_TYPE_NOTIFICATION))
PipelineStepType.AI = PipelineStepType(enums_pb2.STEP_TYPE_AI, api_token('StepType', enums_pb2.STEP_TYPE_AI))
PipelineStepType.DATASOURCE = PipelineStepType(enums_pb2.STEP_TYPE_DATASOURCE, api_token('StepType', enums_pb2.STEP_TYPE_DATASOURCE))
PipelineStepType.SORT = PipelineStepType(enums_pb2.STEP_TYPE_SORT, api_token('StepType', enums_pb2.STEP_TYPE_SORT))
PipelineStepType.RENAME = PipelineStepType(enums_pb2.STEP_TYPE_RENAME, api_token('StepType', enums_pb2.STEP_TYPE_RENAME))
PipelineStepType.EXPRESSION = PipelineStepType(enums_pb2.STEP_TYPE_EXPRESSION, api_token('StepType', enums_pb2.STEP_TYPE_EXPRESSION))
PipelineStepType.WITH_COLUMNS = PipelineStepType(enums_pb2.STEP_TYPE_WITH_COLUMNS, api_token('StepType', enums_pb2.STEP_TYPE_WITH_COLUMNS))
PipelineStepType.FILL_NULL = PipelineStepType(enums_pb2.STEP_TYPE_FILL_NULL, api_token('StepType', enums_pb2.STEP_TYPE_FILL_NULL))
PipelineStepType.DEDUPLICATE = PipelineStepType(enums_pb2.STEP_TYPE_DEDUPLICATE, api_token('StepType', enums_pb2.STEP_TYPE_DEDUPLICATE))
PipelineStepType.STRING_TRANSFORM = PipelineStepType(enums_pb2.STEP_TYPE_STRING_TRANSFORM, api_token('StepType', enums_pb2.STEP_TYPE_STRING_TRANSFORM))
PipelineStepType.TIMESERIES = PipelineStepType(enums_pb2.STEP_TYPE_TIMESERIES, api_token('StepType', enums_pb2.STEP_TYPE_TIMESERIES))
PipelineStepType.PLOT_BAR = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_BAR, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_BAR))
PipelineStepType.PLOT_HORIZONTAL_BAR = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_HORIZONTAL_BAR, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_HORIZONTAL_BAR))
PipelineStepType.PLOT_AREA = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_AREA, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_AREA))
PipelineStepType.PLOT_HEATGRID = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_HEATGRID, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_HEATGRID))
PipelineStepType.PLOT_HISTOGRAM = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_HISTOGRAM, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_HISTOGRAM))
PipelineStepType.PLOT_SCATTER = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_SCATTER, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_SCATTER))
PipelineStepType.PLOT_LINE = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_LINE, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_LINE))
PipelineStepType.PLOT_PIE = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_PIE, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_PIE))
PipelineStepType.PLOT_BOXPLOT = PipelineStepType(enums_pb2.STEP_TYPE_PLOT_BOXPLOT, api_token('StepType', enums_pb2.STEP_TYPE_PLOT_BOXPLOT))


@dataclass(frozen=True, slots=True)
class StepType:
    value: str
    label: str
    normalized: str | None = None
    chart_type: ChartType | None = None
    dependency_config_keys: tuple[str, ...] = ()

    @property
    def canonical(self) -> str:
        return self.normalized or self.value

    @property
    def is_plot_alias(self) -> bool:
        return self.chart_type is not None


_TIMING_SUFFIX_RE = re.compile(r'^(?P<base>.+?)_(?P<index>\d+)$')


@dataclass(frozen=True, slots=True)
class StepTypes:
    select: StepType = StepType(value=PipelineStepType.SELECT.value, label='Select')
    drop: StepType = StepType(value=PipelineStepType.DROP.value, label='Drop')
    filter: StepType = StepType(value=PipelineStepType.FILTER.value, label='Filter')
    groupby: StepType = StepType(value=PipelineStepType.GROUPBY.value, label='Group By')
    join: StepType = StepType(value=PipelineStepType.JOIN.value, label='Join', dependency_config_keys=('right_source',))
    union_by_name: StepType = StepType(value=PipelineStepType.UNION_BY_NAME.value, label='Union By Name', dependency_config_keys=('sources',))
    unpivot: StepType = StepType(value=PipelineStepType.UNPIVOT.value, label='Unpivot')
    explode: StepType = StepType(value=PipelineStepType.EXPLODE.value, label='Explode')
    pivot: StepType = StepType(value=PipelineStepType.PIVOT.value, label='Pivot')
    sample: StepType = StepType(value=PipelineStepType.SAMPLE.value, label='Sample')
    limit: StepType = StepType(value=PipelineStepType.LIMIT.value, label='Limit')
    topk: StepType = StepType(value=PipelineStepType.TOPK.value, label='Top K')
    view: StepType = StepType(value=PipelineStepType.VIEW.value, label='View')
    export: StepType = StepType(value=PipelineStepType.EXPORT.value, label='Export')
    download: StepType = StepType(value=PipelineStepType.DOWNLOAD.value, label='Download')
    chart: StepType = StepType(value=PipelineStepType.CHART.value, label='Chart')
    notification: StepType = StepType(value=PipelineStepType.NOTIFICATION.value, label='Notify')
    ai: StepType = StepType(value=PipelineStepType.AI.value, label='AI')
    datasource: StepType = StepType(value=PipelineStepType.DATASOURCE.value, label='Datasource')
    sort: StepType = StepType(value=PipelineStepType.SORT.value, label='Sort')
    rename: StepType = StepType(value=PipelineStepType.RENAME.value, label='Rename')
    expression: StepType = StepType(value=PipelineStepType.EXPRESSION.value, label='Expression')
    with_columns: StepType = StepType(value=PipelineStepType.WITH_COLUMNS.value, label='With Columns')
    fill_null: StepType = StepType(value=PipelineStepType.FILL_NULL.value, label='Fill Null')
    deduplicate: StepType = StepType(value=PipelineStepType.DEDUPLICATE.value, label='Deduplicate')
    string_transform: StepType = StepType(value=PipelineStepType.STRING_TRANSFORM.value, label='String Transform')
    timeseries: StepType = StepType(value=PipelineStepType.TIMESERIES.value, label='Time Series')
    plot_bar: StepType = StepType(value=PipelineStepType.PLOT_BAR.value, label='Bar Chart', normalized=PipelineStepType.CHART.value, chart_type=ChartType.BAR)
    plot_horizontal_bar: StepType = StepType(
        value=PipelineStepType.PLOT_HORIZONTAL_BAR.value,
        label='Horizontal Bar Chart',
        normalized=PipelineStepType.CHART.value,
        chart_type=ChartType.HORIZONTAL_BAR,
    )
    plot_area: StepType = StepType(
        value=PipelineStepType.PLOT_AREA.value, label='Area Chart', normalized=PipelineStepType.CHART.value, chart_type=ChartType.AREA
    )
    plot_heatgrid: StepType = StepType(
        value=PipelineStepType.PLOT_HEATGRID.value, label='Heatgrid', normalized=PipelineStepType.CHART.value, chart_type=ChartType.HEATGRID
    )
    plot_histogram: StepType = StepType(
        value=PipelineStepType.PLOT_HISTOGRAM.value, label='Histogram', normalized=PipelineStepType.CHART.value, chart_type=ChartType.HISTOGRAM
    )
    plot_scatter: StepType = StepType(
        value=PipelineStepType.PLOT_SCATTER.value, label='Scatter Plot', normalized=PipelineStepType.CHART.value, chart_type=ChartType.SCATTER
    )
    plot_line: StepType = StepType(
        value=PipelineStepType.PLOT_LINE.value, label='Line Chart', normalized=PipelineStepType.CHART.value, chart_type=ChartType.LINE
    )
    plot_pie: StepType = StepType(value=PipelineStepType.PLOT_PIE.value, label='Pie Chart', normalized=PipelineStepType.CHART.value, chart_type=ChartType.PIE)
    plot_boxplot: StepType = StepType(
        value=PipelineStepType.PLOT_BOXPLOT.value, label='Box Plot', normalized=PipelineStepType.CHART.value, chart_type=ChartType.BOXPLOT
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

    def dependency_config_keys(self, step_type: str) -> tuple[str, ...]:
        definition = self._definition_for(step_type)
        return definition.dependency_config_keys if definition is not None else ()

    def dependency_values(self, step_type: str, config: dict[str, object]) -> tuple[str, ...]:
        values: list[str] = []
        for key in self.dependency_config_keys(step_type):
            raw_value = config.get(key)
            if isinstance(raw_value, str) and raw_value:
                values.append(raw_value)
            elif isinstance(raw_value, list):
                values.extend(value for value in raw_value if isinstance(value, str) and value)
        return tuple(values)

    def label(self, step_type: str) -> str:
        definition = self._definition_for(step_type)
        if definition is not None:
            return definition.label
        return ' '.join(part.capitalize() for part in step_type.split('_') if part) or 'Unnamed Step'

    def timing_key(self, key: str) -> tuple[str, str]:
        match = _TIMING_SUFFIX_RE.match(key)
        base_key = match.group('base') if match else key
        suffix = int(match.group('index')) if match else None
        label = self.label(base_key)
        if suffix is not None:
            label = f'{label} {suffix}'
        return base_key, label


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


def get_step_dependency_values(step_type: str, config: dict[str, object]) -> tuple[str, ...]:
    return STEP_TYPES.dependency_values(step_type, config)


def get_step_timing_key(key: str) -> tuple[str, str]:
    return STEP_TYPES.timing_key(key)
