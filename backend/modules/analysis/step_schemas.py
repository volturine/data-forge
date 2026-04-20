from __future__ import annotations

from enum import StrEnum
from typing import TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field

from modules.analysis.step_types import (
    STEP_TYPES,
    ChartType,
    is_step_type,
    iter_step_types,
)
from modules.compute.operations.strings import StringTransformMethod
from modules.compute.operations.timeseries import DurationUnit, TimeComponent, TimeDirection, TimeseriesOperationType
from modules.compute.operations.with_columns import WithColumnsExprType

__all__ = ['get_config_model', 'get_step_catalog', 'validate_step']


class StepCategory(StrEnum):
    TRANSFORM = 'transform'
    AGGREGATE = 'aggregate'
    RESHAPE = 'reshape'
    IO = 'io'
    VISUALIZATION = 'visualization'
    ADVANCED = 'advanced'


class CastMapType(StrEnum):
    INT64 = 'Int64'
    FLOAT64 = 'Float64'
    BOOLEAN = 'Boolean'
    STRING = 'String'
    UTF8 = 'Utf8'
    DATE = 'Date'
    DATETIME = 'Datetime'


class FilterValueType(StrEnum):
    STRING = 'string'
    NUMBER = 'number'
    DATE = 'date'
    DATETIME = 'datetime'
    COLUMN = 'column'
    BOOLEAN = 'boolean'


class FilterLogic(StrEnum):
    AND = 'AND'
    OR = 'OR'


class JoinHow(StrEnum):
    INNER = 'inner'
    LEFT = 'left'
    RIGHT = 'right'
    OUTER = 'outer'
    CROSS = 'cross'


class OverlayChartType(StrEnum):
    LINE = 'line'
    AREA = 'area'
    BAR = 'bar'
    SCATTER = 'scatter'


class YAxisPosition(StrEnum):
    LEFT = 'left'
    RIGHT = 'right'


class ReferenceAxis(StrEnum):
    X = 'x'
    Y = 'y'


class SortDirection(StrEnum):
    ASC = 'asc'
    DESC = 'desc'


class StackMode(StrEnum):
    GROUPED = 'grouped'
    STACKED = 'stacked'
    STACKED_100 = '100%'


class AxisScale(StrEnum):
    LINEAR = 'linear'
    LOG = 'log'


class LegendPosition(StrEnum):
    TOP = 'top'
    BOTTOM = 'bottom'
    LEFT = 'left'
    RIGHT = 'right'
    NONE = 'none'


class ChartHeight(StrEnum):
    SMALL = 'small'
    MEDIUM = 'medium'
    LARGE = 'large'
    XLARGE = 'xlarge'


class ChartWidth(StrEnum):
    NORMAL = 'normal'
    WIDE = 'wide'
    FULL = 'full'


class NotificationMethod(StrEnum):
    EMAIL = 'email'
    TELEGRAM = 'telegram'


class RecipientSource(StrEnum):
    MANUAL = 'manual'
    COLUMN = 'column'


class AIProvider(StrEnum):
    OLLAMA = 'ollama'
    OPENAI = 'openai'
    OPENROUTER = 'openrouter'
    HUGGINGFACE = 'huggingface'


StepCatalogEntry: TypeAlias = dict[str, str | type[BaseModel]]
StepCatalogItem: TypeAlias = dict[str, str | dict[str, object]]


class SelectConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    columns: list[str] = Field(default_factory=list, description='Columns to keep')
    cast_map: dict[str, CastMapType] = Field(
        default_factory=dict,
        description='Optional per-column cast map applied after selection',
    )


class DropConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    columns: list[str] = Field(default_factory=list, description='Columns to remove')


class FilterConditionSchema(BaseModel):
    model_config = ConfigDict(extra='allow')

    column: str = Field(description='Column to filter on')
    operator: str = Field(description='Comparison operator')
    value: str | int | float | bool | list[str] | None = ''
    value_type: FilterValueType = FilterValueType.STRING
    compare_column: str | None = None


class FilterConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    conditions: list[FilterConditionSchema] = Field(
        default_factory=list,
        description='Filter conditions to apply',
    )
    logic: FilterLogic = FilterLogic.AND


class AggregationSchema(BaseModel):
    model_config = ConfigDict(extra='allow')

    column: str = Field(description='Column to aggregate')
    function: str = Field(description='Aggregation function')
    alias: str = Field(description='Output column name')


class GroupByConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    group_by: list[str] = Field(
        default_factory=list,
        description='Columns to group by',
    )
    aggregations: list[AggregationSchema] = Field(
        default_factory=list,
        description='Aggregation expressions',
    )


class SortConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    columns: list[str] = Field(default_factory=list, description='Columns to sort by')
    descending: list[bool] | bool = Field(
        default_factory=list,
        description='Descending flag per column (or single bool for all)',
    )


class RenameConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    column_mapping: dict[str, str] = Field(
        default_factory=dict,
        description='Old name to new name mapping',
    )


class ExpressionConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    expression: str = Field('', description='Polars expression string')
    column_name: str = Field('', description='Output column name')


class WithColumnsExprSchema(BaseModel):
    model_config = ConfigDict(extra='allow')

    name: str = Field(description='Output column name')
    type: WithColumnsExprType = WithColumnsExprType.LITERAL
    value: str | int | float | None = None
    column: str | None = None
    args: list[str] | None = None
    code: str | None = None
    udf_id: str | None = None


class WithColumnsConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    expressions: list[WithColumnsExprSchema] = Field(
        default_factory=list,
        description='Column expressions to add or replace',
    )


class LimitConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    n: int = Field(100, description='Maximum number of rows')


class SampleConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    fraction: float = Field(0.5, description='Fraction of rows to sample (0–1)')
    seed: int | None = None


class TopKConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    column: str = Field('', description='Column to rank by')
    k: int = Field(10, description='Number of top rows')
    descending: bool = False


class DeduplicateConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    subset: list[str] | None = Field(None, description='Columns to check for duplicates')
    keep: str = Field('first', description='Which duplicate to keep: first, last, none')


class FillNullConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    strategy: str = Field(
        'literal',
        description='Fill strategy: literal, forward, backward, mean, min, max',
    )
    columns: list[str] | None = None
    value: str | int | float | None = None
    value_type: str | None = None


class UnpivotConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    id_vars: list[str] = Field(default_factory=list, description='Identifier columns to keep')
    value_vars: list[str] = Field(
        default_factory=list,
        description='Columns to unpivot into rows',
    )
    variable_name: str = 'variable'
    value_name: str = 'value'


class ExplodeConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    columns: list[str] = Field(
        default_factory=list,
        description='List columns to explode into rows',
    )


class PivotConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    index: list[str] = Field(default_factory=list, description='Row identifier columns')
    columns: str = Field('', description='Column to pivot on')
    values: str | None = Field(None, description='Values to aggregate')
    aggregate_function: str = Field(
        'first',
        description='Aggregation function for pivoted values',
    )


class UnionByNameConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    sources: list[str] = Field(default_factory=list, description='Tab IDs to union')
    allow_missing: bool = True


class JoinColumnSchema(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str = Field(description='Unique join column pair ID')
    left_column: str = Field(description='Column from left table')
    right_column: str = Field(description='Column from right table')


class JoinConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    how: JoinHow = JoinHow.INNER
    right_source: str = Field('', description='Tab ID to join with')
    join_columns: list[JoinColumnSchema] = Field(
        default_factory=list,
        description='Column pairs to join on',
    )
    right_columns: list[str] = Field(
        default_factory=list,
        description='Columns to select from right table',
    )
    suffix: str = '_right'


class ViewConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    row_limit: int | None = Field(100, alias='rowLimit', description='Max rows to preview')


class ExportConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    format: str = Field('csv', description='Output format: csv, parquet, json')
    filename: str = 'export'
    destination: str = 'download'


class DownloadConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    format: str = Field('csv', description='Output format: csv, parquet, json')
    filename: str = 'download'


class OverlaySchema(BaseModel):
    model_config = ConfigDict(extra='allow')

    chart_type: OverlayChartType = OverlayChartType.LINE
    y_column: str = ''
    aggregation: str = 'sum'
    y_axis_position: YAxisPosition = YAxisPosition.LEFT


class ReferenceLineSchema(BaseModel):
    model_config = ConfigDict(extra='allow')

    axis: ReferenceAxis = ReferenceAxis.Y
    value: float | None = None
    label: str = ''
    color: str = ''


class ChartConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    chart_type: ChartType = Field(ChartType.BAR, description='Visualization type')
    x_column: str = Field('', description='X-axis column')
    y_column: str = Field('', description='Y-axis column')
    bins: int = 10
    aggregation: str = 'sum'
    group_column: str | None = None
    group_sort_by: str | None = None
    group_sort_order: SortDirection = SortDirection.ASC
    group_sort_column: str | None = None
    stack_mode: StackMode = StackMode.GROUPED
    area_opacity: float = 0.35
    date_bucket: str | None = None
    date_ordinal: str | None = None
    pan_zoom_enabled: bool = False
    selection_enabled: bool = False
    area_selection_enabled: bool = False
    sort_by: str | None = None
    sort_order: SortDirection = SortDirection.ASC
    sort_column: str | None = None
    x_axis_label: str | None = ''
    y_axis_label: str | None = ''
    y_axis_scale: AxisScale = AxisScale.LINEAR
    y_axis_min: float | None = None
    y_axis_max: float | None = None
    display_units: str = ''
    decimal_places: int = 2
    legend_position: LegendPosition = LegendPosition.RIGHT
    title: str | None = ''
    series_colors: list[str] = Field(default_factory=list)
    overlays: list[OverlaySchema] = Field(default_factory=list)
    reference_lines: list[ReferenceLineSchema] = Field(default_factory=list)
    chart_height: ChartHeight = ChartHeight.MEDIUM
    chart_width: ChartWidth = ChartWidth.NORMAL


class NotificationConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    method: NotificationMethod = NotificationMethod.EMAIL
    recipient: str = ''
    subscriber_ids: list[str] = Field(default_factory=list)
    bot_token: str = ''
    recipient_source: RecipientSource = RecipientSource.MANUAL
    recipient_column: str = ''
    input_columns: list[str] = Field(
        default_factory=list,
        description='Columns to include in notification',
    )
    output_column: str = 'notification_status'
    message_template: str = '{{message}}'
    subject_template: str = 'Notification'
    batch_size: int = 10
    timeout_seconds: int = 20


class AIConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    provider: AIProvider = AIProvider.OLLAMA
    model: str = 'llama2'
    input_columns: list[str] = Field(
        default_factory=list,
        description='Columns to feed into the prompt',
    )
    output_column: str = 'ai_result'
    error_column: str = 'ai_error'
    prompt_template: str = 'Classify this text: {{text}}'
    batch_size: int = 10
    max_retries: int = 3
    rate_limit_rpm: int | None = None
    endpoint_url: str = ''
    api_key: str = ''
    temperature: float = 0.7
    max_tokens: int | None = None
    request_options: dict | None = None


class DatasourceConfig(BaseModel):
    model_config = ConfigDict(extra='allow')


class TimeSeriesConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    column: str = Field('', description='Date/time column to operate on')
    operation_type: TimeseriesOperationType = Field(description='Temporal operation type')
    new_column: str = ''
    component: TimeComponent | None = None
    value: int | None = None
    unit: DurationUnit | None = None
    direction: TimeDirection | None = None
    column2: str | None = None


class StringTransformConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    column: str = Field('', description='String column to transform')
    method: StringTransformMethod = Field(description='String method to apply')
    new_column: str = ''
    start: int | None = None
    end: int | None = None
    pattern: str | None = None
    replacement: str | None = None
    group_index: int | None = None
    delimiter: str | None = None
    index: int | None = None


STEP_CATALOG: dict[str, StepCatalogEntry] = {
    'select': {
        'description': 'Keep only the specified columns, removing all others.',
        'category': 'transform',
        'config': SelectConfig,
    },
    'drop': {
        'description': 'Remove the specified columns from the dataset.',
        'category': 'transform',
        'config': DropConfig,
    },
    'filter': {
        'description': (
            'Filter rows using conditions. Supports multiple conditions with AND/OR logic. '
            'Each condition specifies a column, operator (=, !=, >, <, >=, <=, contains, '
            'starts_with, ends_with, is_null, is_not_null, in, not_in), value, and value_type.'
        ),
        'category': 'transform',
        'config': FilterConfig,
    },
    'sort': {
        'description': 'Sort rows by one or more columns with per-column ascending/descending control.',
        'category': 'transform',
        'config': SortConfig,
    },
    'rename': {
        'description': 'Rename columns using an old-name-to-new-name mapping.',
        'category': 'transform',
        'config': RenameConfig,
    },
    'expression': {
        'description': 'Evaluate a Polars expression string and assign the result to a new column.',
        'category': 'transform',
        'config': ExpressionConfig,
    },
    'with_columns': {
        'description': 'Add or replace columns using literal values, column references, or UDFs.',
        'category': 'transform',
        'config': WithColumnsConfig,
    },
    'fill_null': {
        'description': (
            'Fill null values using a strategy: literal value, forward fill, backward fill, mean, min, or max. '
            'Optionally restrict to specific columns.'
        ),
        'category': 'transform',
        'config': FillNullConfig,
    },
    'deduplicate': {
        'description': 'Remove duplicate rows. Optionally specify a column subset and which duplicate to keep.',
        'category': 'transform',
        'config': DeduplicateConfig,
    },
    'string_transform': {
        'description': (
            'Apply string methods to a column: uppercase, lowercase, trim, strip, slice, replace, '
            'extract, split, contains, starts_with, ends_with.'
        ),
        'category': 'transform',
        'config': StringTransformConfig,
    },
    'timeseries': {
        'description': (
            'Perform temporal operations on date/datetime columns: extract components, add/subtract '
            'durations, compute differences, truncate, or round.'
        ),
        'category': 'transform',
        'config': TimeSeriesConfig,
    },
    'limit': {
        'description': 'Return only the first N rows of the dataset.',
        'category': 'transform',
        'config': LimitConfig,
    },
    'sample': {
        'description': 'Randomly sample N rows from the dataset with optional seed and replacement.',
        'category': 'transform',
        'config': SampleConfig,
    },
    'groupby': {
        'description': (
            'Group rows by columns and compute aggregations. Supported functions: sum, mean, min, max, '
            'count, first, last, std, median, n_unique.'
        ),
        'category': 'aggregate',
        'config': GroupByConfig,
    },
    'topk': {
        'description': 'Return the top K rows ranked by a column value.',
        'category': 'aggregate',
        'config': TopKConfig,
    },
    'pivot': {
        'description': 'Pivot long-format data to wide-format using index, column, and value fields.',
        'category': 'reshape',
        'config': PivotConfig,
    },
    'unpivot': {
        'description': 'Unpivot wide-format data to long-format (melt). Specify id vars and value vars.',
        'category': 'reshape',
        'config': UnpivotConfig,
    },
    'explode': {
        'description': 'Explode list-type columns so each list element becomes its own row.',
        'category': 'reshape',
        'config': ExplodeConfig,
    },
    'union_by_name': {
        'description': 'Vertically concatenate datasets by matching column names. Missing columns filled with null.',
        'category': 'reshape',
        'config': UnionByNameConfig,
    },
    'join': {
        'description': (
            'Join with another datasource tab. Supports inner, left, right, outer, and cross join types. Specify column pairs to join on.'
        ),
        'category': 'reshape',
        'config': JoinConfig,
    },
    'export': {
        'description': 'Export the dataset to a file in csv, parquet, or json format.',
        'category': 'io',
        'config': ExportConfig,
    },
    'download': {
        'description': 'Download the dataset as a file in the specified format.',
        'category': 'io',
        'config': DownloadConfig,
    },
    'view': {
        'description': 'Preview rows from the dataset with an optional row limit.',
        'category': 'io',
        'config': ViewConfig,
    },
    'datasource': {
        'description': 'Load data from a configured datasource.',
        'category': 'io',
        'config': DatasourceConfig,
    },
    'chart': {
        'description': (
            'Create a visualization. Supports chart types: bar, horizontal_bar, area, heatgrid, '
            'histogram, scatter, line, pie, boxplot. Configure axes, aggregation, grouping, '
            'sorting, overlays, reference lines, and display options.'
        ),
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_bar': {
        'description': 'Bar chart visualization (alias for chart with chart_type=bar).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_horizontal_bar': {
        'description': 'Horizontal bar chart (alias for chart with chart_type=horizontal_bar).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_area': {
        'description': 'Area chart visualization (alias for chart with chart_type=area).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_heatgrid': {
        'description': 'Heatgrid visualization (alias for chart with chart_type=heatgrid).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_histogram': {
        'description': 'Histogram visualization (alias for chart with chart_type=histogram).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_scatter': {
        'description': 'Scatter plot visualization (alias for chart with chart_type=scatter).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_line': {
        'description': 'Line chart visualization (alias for chart with chart_type=line).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_pie': {
        'description': 'Pie chart visualization (alias for chart with chart_type=pie).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'plot_boxplot': {
        'description': 'Boxplot visualization (alias for chart with chart_type=boxplot).',
        'category': 'visualization',
        'config': ChartConfig,
    },
    'ai': {
        'description': (
            'Run AI inference on rows using Ollama or OpenAI. Configure input columns, prompt template '
            'with {{column}} placeholders, and output column.'
        ),
        'category': 'advanced',
        'config': AIConfig,
    },
    'notification': {
        'description': ('Send notifications via email or Telegram. Configure recipient, message template, and batch processing options.'),
        'category': 'advanced',
        'config': NotificationConfig,
    },
}


def get_step_catalog() -> list[StepCatalogItem]:
    """Return the step type catalog for AI discovery."""
    result: list[StepCatalogItem] = []
    for typ in iter_step_types(include_plot_aliases=False):
        info = STEP_CATALOG[typ]
        config_model = cast(type[BaseModel], info['config'])
        result.append(
            {
                'type': typ,
                'label': STEP_TYPES.label(typ),
                'description': cast(str, info['description']),
                'category': cast(str, info['category']),
                'config_schema': cast(dict[str, object], config_model.model_json_schema()),
            },
        )
    return result


def get_config_model(step_type: str) -> type[BaseModel] | None:
    """Return the config model for a step type."""
    if not is_step_type(step_type):
        return None
    entry = STEP_CATALOG.get(step_type)
    if not entry:
        return None
    return cast(type[BaseModel], entry['config'])


def validate_step(step_type: str, config: dict) -> None:
    """Validate a step type and its config. Raises ValueError on failure."""
    if not is_step_type(step_type):
        raise ValueError(f"Unknown step type '{step_type}'")
    model = cast(type[BaseModel], STEP_CATALOG[step_type]['config'])
    model.model_validate(config)
