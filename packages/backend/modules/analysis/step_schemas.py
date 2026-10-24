from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend_core.domain.analysis.step_types import (
    STEP_TYPES,
    ChartType,
)
from backend_core.domain.compute.schemas import ExportDestination, ExportFormat
from backend_core.domain.step_config_enums import (
    AIProvider,
    AxisScale,
    CastMapType,
    ChartAggregation,
    ChartHeight,
    ChartWidth,
    DateBucket,
    DateOrdinal,
    DeduplicateKeep,
    DisplayUnits,
    DurationUnit,
    FillNullStrategy,
    FilterLogic,
    FilterOperator,
    FilterValueType,
    GroupByAggregationFunction,
    GroupSortBy,
    JoinHow,
    LegendPosition,
    NotificationMethod,
    OverlayChartType,
    PivotAggregateFunction,
    RecipientSource,
    ReferenceAxis,
    SortBy,
    SortDirection,
    StackMode,
    StringTransformMethod,
    TimeComponent,
    TimeDirection,
    TimeseriesOperationType,
    WithColumnsExprType,
    YAxisPosition,
)

__all__ = [
    'get_step_catalog',
    'normalize_step_config',
    'normalize_step_config_for_protocol',
    'normalize_pipeline_step_configs_for_protocol',
]


@dataclass(frozen=True, slots=True)
class StepCatalogEntry:
    description: str
    category: str
    config: type[BaseModel]


type StepCatalogItem = dict[str, str | dict[str, object]]


class SelectConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    columns: list[str] = Field(default_factory=list, description='Columns to keep')
    cast_map: dict[str, CastMapType] = Field(
        default_factory=dict,
        description='Optional per-column cast map applied after selection',
    )


class DropConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    columns: list[str] = Field(default_factory=list, description='Columns to remove')


class FilterConditionSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @model_validator(mode='before')
    @classmethod
    def strip_ui_metadata(cls, data: object) -> object:
        if not isinstance(data, dict) or 'dtype' not in data:
            return data
        return {key: value for key, value in data.items() if key != 'dtype'}

    column: str = Field(description='Column to filter on')
    operator: FilterOperator = Field(description='Comparison operator')
    value: str | int | float | bool | list[str] | None = ''
    value_type: FilterValueType = FilterValueType.STRING
    compare_column: str | None = None


class FilterConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    conditions: list[FilterConditionSchema] = Field(
        default_factory=list,
        description='Filter conditions to apply',
    )
    logic: FilterLogic = FilterLogic.AND


class AggregationSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str = Field(description='Column to aggregate')
    function: GroupByAggregationFunction = Field(description='Aggregation function')
    alias: str = Field(description='Output column name')


class GroupByConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    group_by: list[str] = Field(
        default_factory=list,
        description='Columns to group by',
    )
    aggregations: list[AggregationSchema] = Field(
        default_factory=list,
        description='Aggregation expressions',
    )


class SortConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    columns: list[str] = Field(default_factory=list, description='Columns to sort by')
    descending: list[bool] | bool = Field(
        default_factory=list,
        description='Descending flag per column (or single bool for all)',
    )


class RenameConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column_mapping: dict[str, str] = Field(
        default_factory=dict,
        description='Old name to new name mapping',
    )


class ExpressionConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expression: str = Field('', description='Polars expression string')
    column_name: str = Field('', description='Output column name')


class WithColumnsExprSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(description='Output column name')
    type: WithColumnsExprType = WithColumnsExprType.LITERAL
    value: str | int | float | None = None
    column: str | None = None
    args: list[str] | None = None
    code: str | None = None
    udf_id: str | None = None


class WithColumnsConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expressions: list[WithColumnsExprSchema] = Field(
        default_factory=list,
        description='Column expressions to add or replace',
    )


class LimitConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    n: int = Field(100, description='Maximum number of rows')


class SampleConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    fraction: float = Field(0.5, description='Fraction of rows to sample (0–1)')
    seed: int | None = None


class TopKConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str = Field('', description='Column to rank by')
    k: int = Field(10, description='Number of top rows')
    descending: bool = False


class DeduplicateConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    subset: list[str] | None = Field(None, description='Columns to check for duplicates')
    keep: DeduplicateKeep = Field(DeduplicateKeep.FIRST, description='Which duplicate to keep: first, last, none')


class FillNullConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    strategy: FillNullStrategy = Field(
        FillNullStrategy.LITERAL,
        description='Fill strategy: literal, forward, backward, mean, min, max',
    )
    columns: list[str] | None = None
    value: str | int | float | None = None
    value_type: str | None = None


class UnpivotConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id_vars: list[str] = Field(default_factory=list, description='Identifier columns to keep')
    value_vars: list[str] = Field(
        default_factory=list,
        description='Columns to unpivot into rows',
    )
    variable_name: str = 'variable'
    value_name: str = 'value'

    @model_validator(mode='before')
    @classmethod
    def normalize_polars_names(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if 'id_vars' in data or 'value_vars' in data:
            return data
        if 'index' not in data and 'on' not in data:
            return data
        return {
            'id_vars': data.get('index', []),
            'value_vars': data.get('on', []),
            'variable_name': data.get('variable_name', 'variable'),
            'value_name': data.get('value_name', 'value'),
        }


class ExplodeConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    columns: list[str] = Field(
        default_factory=list,
        description='List columns to explode into rows',
    )


class PivotConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    index: list[str] = Field(default_factory=list, description='Row identifier columns')
    columns: str = Field('', description='Column to pivot on')
    value_columns: list[str] = Field(default_factory=list, description='Value columns to aggregate')
    aggregate_function: PivotAggregateFunction = Field(
        PivotAggregateFunction.FIRST,
        description='Aggregation function for pivoted values',
    )


class UnionByNameConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    sources: list[str] = Field(default_factory=list, description='Tab IDs to union')
    allow_missing: bool = True


class JoinColumnSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(description='Unique join column pair ID')
    left_column: str = Field(description='Column from left table')
    right_column: str = Field(description='Column from right table')


class JoinConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

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
    model_config = ConfigDict(extra='forbid')

    row_limit: int | None = Field(100, alias='rowLimit', description='Max rows to preview')
    cache_enabled: bool = Field(True, alias='cacheEnabled', description='Reuse complete preview results')


class ExportConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    format: ExportFormat = Field(ExportFormat.CSV, description='Output format')
    filename: str = 'export'
    destination: ExportDestination = ExportDestination.DOWNLOAD


class DownloadConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    format: ExportFormat = Field(ExportFormat.CSV, description='Output format')
    filename: str = 'download'


class OverlaySchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    chart_type: OverlayChartType = OverlayChartType.LINE
    y_column: str = ''
    aggregation: ChartAggregation = ChartAggregation.SUM
    y_axis_position: YAxisPosition = YAxisPosition.LEFT


class ReferenceLineSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    axis: ReferenceAxis = ReferenceAxis.Y
    value: float | None = None
    label: str = ''
    color: str = ''


class ChartConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    chart_type: ChartType = Field(ChartType.BAR, description='Visualization type')
    x_column: str = Field('', description='X-axis column')
    y_column: str = Field('', description='Y-axis column')
    bins: int = 10
    aggregation: ChartAggregation = ChartAggregation.SUM
    group_column: str | None = None
    group_sort_by: GroupSortBy | None = None
    group_sort_order: SortDirection = SortDirection.ASC
    group_sort_column: str | None = None
    stack_mode: StackMode = StackMode.GROUPED
    area_opacity: float = 0.35
    date_bucket: DateBucket | None = None
    date_ordinal: DateOrdinal | None = None
    pan_zoom_enabled: bool = False
    selection_enabled: bool = False
    area_selection_enabled: bool = False
    sort_by: SortBy | None = None
    sort_order: SortDirection = SortDirection.ASC
    sort_column: str | None = None
    x_axis_label: str | None = ''
    y_axis_label: str | None = ''
    y_axis_scale: AxisScale = AxisScale.LINEAR
    y_axis_min: float | None = None
    y_axis_max: float | None = None
    display_units: DisplayUnits = DisplayUnits.NONE
    decimal_places: int = 2
    legend_position: LegendPosition = LegendPosition.RIGHT
    title: str | None = ''
    series_colors: list[str] = Field(default_factory=list)
    overlays: list[OverlaySchema] = Field(default_factory=list)
    reference_lines: list[ReferenceLineSchema] = Field(default_factory=list)
    chart_height: ChartHeight = ChartHeight.MEDIUM
    chart_width: ChartWidth = ChartWidth.NORMAL


class NotificationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

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


class AIConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

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
    model_config = ConfigDict(extra='forbid')


class TimeSeriesConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str = Field('', description='Date/time column to operate on')
    operation_type: TimeseriesOperationType = Field(description='Temporal operation type')
    new_column: str = ''
    component: TimeComponent | None = None
    value: int | None = None
    unit: DurationUnit | None = None
    direction: TimeDirection | None = None
    column2: str | None = None


class StringTransformConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

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
    'select': StepCatalogEntry(
        description='Keep only the specified columns, removing all others.',
        category='transform',
        config=SelectConfig,
    ),
    'drop': StepCatalogEntry(
        description='Remove the specified columns from the dataset.',
        category='transform',
        config=DropConfig,
    ),
    'filter': StepCatalogEntry(
        description=(
            'Filter rows using conditions. Supports multiple conditions with AND/OR logic. '
            'Each condition specifies a column, operator (=, !=, >, <, >=, <=, contains, '
            'starts_with, ends_with, is_null, is_not_null, in, not_in), value, and value_type.'
        ),
        category='transform',
        config=FilterConfig,
    ),
    'sort': StepCatalogEntry(
        description='Sort rows by one or more columns with per-column ascending/descending control.',
        category='transform',
        config=SortConfig,
    ),
    'rename': StepCatalogEntry(
        description='Rename columns using an old-name-to-new-name mapping.',
        category='transform',
        config=RenameConfig,
    ),
    'expression': StepCatalogEntry(
        description='Evaluate a Polars expression string and assign the result to a new column.',
        category='transform',
        config=ExpressionConfig,
    ),
    'with_columns': StepCatalogEntry(
        description='Add or replace columns using literal values, column references, or UDFs.',
        category='transform',
        config=WithColumnsConfig,
    ),
    'fill_null': StepCatalogEntry(
        description=(
            'Fill null values using a strategy: literal value, forward fill, backward fill, mean, min, or max. Optionally restrict to specific columns.'
        ),
        category='transform',
        config=FillNullConfig,
    ),
    'deduplicate': StepCatalogEntry(
        description='Remove duplicate rows. Optionally specify a column subset and which duplicate to keep.',
        category='transform',
        config=DeduplicateConfig,
    ),
    'string_transform': StepCatalogEntry(
        description=('Apply string methods to a column: uppercase, lowercase, trim, strip, slice, replace, extract, split, contains, starts_with, ends_with.'),
        category='transform',
        config=StringTransformConfig,
    ),
    'timeseries': StepCatalogEntry(
        description=(
            'Perform temporal operations on date/datetime columns: extract components, add/subtract durations, compute differences, truncate, or round.'
        ),
        category='transform',
        config=TimeSeriesConfig,
    ),
    'limit': StepCatalogEntry(
        description='Return only the first N rows of the dataset.',
        category='transform',
        config=LimitConfig,
    ),
    'sample': StepCatalogEntry(
        description='Randomly sample N rows from the dataset with optional seed and replacement.',
        category='transform',
        config=SampleConfig,
    ),
    'groupby': StepCatalogEntry(
        description=(
            'Group rows by columns and compute aggregations. Supported functions: sum, mean, count, min, max, first, last, median, std, '
            'n_unique, collect_list, collect_set.'
        ),
        category='aggregate',
        config=GroupByConfig,
    ),
    'topk': StepCatalogEntry(
        description='Return the top K rows ranked by a column value.',
        category='aggregate',
        config=TopKConfig,
    ),
    'pivot': StepCatalogEntry(
        description='Pivot long-format data to wide-format using index, column, and value fields.',
        category='reshape',
        config=PivotConfig,
    ),
    'unpivot': StepCatalogEntry(
        description='Unpivot wide-format data to long-format (melt). Specify id vars and value vars.',
        category='reshape',
        config=UnpivotConfig,
    ),
    'explode': StepCatalogEntry(
        description='Explode list-type columns so each list element becomes its own row.',
        category='reshape',
        config=ExplodeConfig,
    ),
    'union_by_name': StepCatalogEntry(
        description='Vertically concatenate datasets by matching column names. Missing columns filled with null.',
        category='reshape',
        config=UnionByNameConfig,
    ),
    'join': StepCatalogEntry(
        description=('Join with another datasource tab. Supports inner, left, right, outer, and cross join types. Specify column pairs to join on.'),
        category='reshape',
        config=JoinConfig,
    ),
    'export': StepCatalogEntry(
        description='Export the dataset to a file in csv, parquet, or json format.',
        category='io',
        config=ExportConfig,
    ),
    'download': StepCatalogEntry(
        description='Download the dataset as a file in the specified format.',
        category='io',
        config=DownloadConfig,
    ),
    'view': StepCatalogEntry(
        description='Preview rows from the dataset with an optional row limit.',
        category='io',
        config=ViewConfig,
    ),
    'datasource': StepCatalogEntry(
        description='Load data from a configured datasource.',
        category='io',
        config=DatasourceConfig,
    ),
    'chart': StepCatalogEntry(
        description=(
            'Create a visualization. Supports chart types: bar, horizontal_bar, area, heatgrid, '
            'histogram, scatter, line, pie, boxplot. Configure axes, aggregation, grouping, '
            'sorting, overlays, reference lines, and display options.'
        ),
        category='visualization',
        config=ChartConfig,
    ),
    'ai': StepCatalogEntry(
        description=(
            'Run AI inference on rows using Ollama or OpenRouter. Configure input columns, prompt template with {{column}} placeholders, and output column.'
        ),
        category='advanced',
        config=AIConfig,
    ),
    'notification': StepCatalogEntry(
        description=('Send notifications via email or Telegram. Configure recipient, message template, and batch processing options.'),
        category='advanced',
        config=NotificationConfig,
    ),
}


def get_step_catalog() -> list[StepCatalogItem]:
    """Return the step type catalog for AI discovery."""
    result: list[StepCatalogItem] = []
    for typ in STEP_TYPES.all(include_plot_aliases=False):
        info = STEP_CATALOG[typ]
        result.append(
            {
                'type': typ,
                'label': STEP_TYPES.label(typ),
                'description': info.description,
                'category': info.category,
                'config_schema': info.config.model_json_schema(),
            },
        )
    return result


def _config_model(step_type: str) -> type[BaseModel]:
    """Return the config schema for a step type; plot aliases share the chart schema."""
    if not STEP_TYPES.has(step_type):
        raise ValueError(f"Unknown step type '{step_type}'")
    return STEP_CATALOG[STEP_TYPES.normalized(step_type)].config


def normalize_step_config(step_type: str, config: dict) -> dict[str, object]:
    """Validate and return the canonical config for a step type."""
    return _config_model(step_type).model_validate(config).model_dump(mode='json', by_alias=True)


def _filter_value_for_protocol(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {'bool_value': value}
    if isinstance(value, int | float):
        return {'number_value': value}
    if isinstance(value, str):
        return {'string_value': value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return {'string_values': {'values': value}}
    raise ValueError(f'Unsupported protocol filter value: {value!r}')


def normalize_step_config_for_protocol(step_type: str, config: dict) -> dict[str, object]:
    """Validate an HTTP operation config and serialize its typed protocol fields."""
    validated_config = _config_model(step_type).model_validate(config)
    payload = cast(
        dict[str, object],
        validated_config.model_dump(
            mode='python',
            by_alias=False,
            context={'protocol_enum_numbers': True},
        ),
    )
    normalized_type = STEP_TYPES.normalized(step_type)
    if normalized_type == STEP_TYPES.filter.value:
        for condition in cast(list[dict[str, object]], payload.get('conditions', [])):
            if 'value' in condition:
                condition['value'] = _filter_value_for_protocol(condition['value'])
    elif normalized_type == STEP_TYPES.with_columns.value:
        for expression in cast(list[dict[str, object]], payload.get('expressions', [])):
            if 'value' in expression:
                expression['value'] = _filter_value_for_protocol(expression['value'])
    elif normalized_type == STEP_TYPES.fill_null.value and 'value' in payload:
        payload['value'] = _filter_value_for_protocol(payload['value'])
    elif normalized_type == STEP_TYPES.select.value:
        # SelectConfig.cast_map is intentionally a string map in the wire schema.
        cast_map = validated_config.model_dump(mode='json', by_alias=True).get('cast_map')
        if isinstance(cast_map, dict):
            payload['cast_map'] = cast_map
    return payload


def normalize_pipeline_step_configs_for_protocol(pipeline: dict[str, object]) -> dict[str, object]:
    """Canonicalize HTTP step configs before protocol transport or persistence."""
    normalized = dict(pipeline)
    raw_tabs = pipeline.get('tabs')
    if not isinstance(raw_tabs, list):
        return normalized
    tabs: list[object] = []
    for raw_tab in raw_tabs:
        if not isinstance(raw_tab, dict):
            tabs.append(raw_tab)
            continue
        tab = dict(raw_tab)
        raw_steps = raw_tab.get('steps')
        if isinstance(raw_steps, list):
            steps: list[object] = []
            for raw_step in raw_steps:
                if not isinstance(raw_step, dict):
                    steps.append(raw_step)
                    continue
                step = dict(raw_step)
                step_type = step.get('type')
                config = step.get('config')
                if isinstance(step_type, str) and isinstance(config, dict):
                    step['config'] = normalize_step_config_for_protocol(step_type, config)
                steps.append(step)
            tab['steps'] = steps
        tabs.append(tab)
    normalized['tabs'] = tabs
    return normalized
