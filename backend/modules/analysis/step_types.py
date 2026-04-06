from __future__ import annotations

from enum import StrEnum
from typing import Final, TypeAlias, TypeGuard


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


class CanonicalStepType(StrEnum):
    SELECT = 'select'
    DROP = 'drop'
    FILTER = 'filter'
    GROUPBY = 'groupby'
    JOIN = 'join'
    UNION_BY_NAME = 'union_by_name'
    UNPIVOT = 'unpivot'
    EXPLODE = 'explode'
    PIVOT = 'pivot'
    SAMPLE = 'sample'
    LIMIT = 'limit'
    TOPK = 'topk'
    VIEW = 'view'
    EXPORT = 'export'
    DOWNLOAD = 'download'
    CHART = 'chart'
    NOTIFICATION = 'notification'
    AI = 'ai'
    DATASOURCE = 'datasource'
    SORT = 'sort'
    RENAME = 'rename'
    EXPRESSION = 'expression'
    WITH_COLUMNS = 'with_columns'
    FILL_NULL = 'fill_null'
    DEDUPLICATE = 'deduplicate'
    STRING_TRANSFORM = 'string_transform'
    TIMESERIES = 'timeseries'


class PlotAliasStepType(StrEnum):
    PLOT_BAR = 'plot_bar'
    PLOT_HORIZONTAL_BAR = 'plot_horizontal_bar'
    PLOT_AREA = 'plot_area'
    PLOT_HEATGRID = 'plot_heatgrid'
    PLOT_HISTOGRAM = 'plot_histogram'
    PLOT_SCATTER = 'plot_scatter'
    PLOT_LINE = 'plot_line'
    PLOT_PIE = 'plot_pie'
    PLOT_BOXPLOT = 'plot_boxplot'


StepType: TypeAlias = CanonicalStepType | PlotAliasStepType

PLOT_ALIAS_TO_CHART_TYPE: Final[dict[PlotAliasStepType, ChartType]] = {
    PlotAliasStepType.PLOT_BAR: ChartType.BAR,
    PlotAliasStepType.PLOT_HORIZONTAL_BAR: ChartType.HORIZONTAL_BAR,
    PlotAliasStepType.PLOT_AREA: ChartType.AREA,
    PlotAliasStepType.PLOT_HEATGRID: ChartType.HEATGRID,
    PlotAliasStepType.PLOT_HISTOGRAM: ChartType.HISTOGRAM,
    PlotAliasStepType.PLOT_SCATTER: ChartType.SCATTER,
    PlotAliasStepType.PLOT_LINE: ChartType.LINE,
    PlotAliasStepType.PLOT_PIE: ChartType.PIE,
    PlotAliasStepType.PLOT_BOXPLOT: ChartType.BOXPLOT,
}

_CANONICAL_STEP_TYPES: Final[frozenset[str]] = frozenset(
    {
        CanonicalStepType.SELECT,
        CanonicalStepType.DROP,
        CanonicalStepType.FILTER,
        CanonicalStepType.GROUPBY,
        CanonicalStepType.JOIN,
        CanonicalStepType.UNION_BY_NAME,
        CanonicalStepType.UNPIVOT,
        CanonicalStepType.EXPLODE,
        CanonicalStepType.PIVOT,
        CanonicalStepType.SAMPLE,
        CanonicalStepType.LIMIT,
        CanonicalStepType.TOPK,
        CanonicalStepType.VIEW,
        CanonicalStepType.EXPORT,
        CanonicalStepType.DOWNLOAD,
        CanonicalStepType.CHART,
        CanonicalStepType.NOTIFICATION,
        CanonicalStepType.AI,
        CanonicalStepType.DATASOURCE,
        CanonicalStepType.SORT,
        CanonicalStepType.RENAME,
        CanonicalStepType.EXPRESSION,
        CanonicalStepType.WITH_COLUMNS,
        CanonicalStepType.FILL_NULL,
        CanonicalStepType.DEDUPLICATE,
        CanonicalStepType.STRING_TRANSFORM,
        CanonicalStepType.TIMESERIES,
    },
)


def is_plot_alias_step_type(step_type: str) -> TypeGuard[PlotAliasStepType]:
    return step_type in PLOT_ALIAS_TO_CHART_TYPE


def is_chart_step_type(step_type: str) -> bool:
    return step_type == CanonicalStepType.CHART or is_plot_alias_step_type(step_type)


def is_step_type(step_type: str) -> TypeGuard[StepType]:
    return step_type in _CANONICAL_STEP_TYPES or is_plot_alias_step_type(step_type)


def normalize_step_type(step_type: str) -> str:
    return CanonicalStepType.CHART if is_plot_alias_step_type(step_type) else step_type


def chart_type_for_step(step_type: str) -> ChartType | None:
    if not is_plot_alias_step_type(step_type):
        return None
    return PLOT_ALIAS_TO_CHART_TYPE[step_type]
