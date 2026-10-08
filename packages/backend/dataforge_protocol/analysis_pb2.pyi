from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import enums_pb2 as _enums_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AnalysisPipelineDatasource(_message.Message):
    __slots__ = ("id", "analysis_tab_id", "source_type", "config")
    ID_FIELD_NUMBER: _ClassVar[int]
    ANALYSIS_TAB_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    id: str
    analysis_tab_id: str
    source_type: _enums_pb2.DataSourceType
    config: _struct_pb2.Struct
    def __init__(self, id: _Optional[str] = ..., analysis_tab_id: _Optional[str] = ..., source_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class AnalysisPipelineStep(_message.Message):
    __slots__ = ("id", "config", "depends_on", "is_applied", "step_type")
    ID_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    DEPENDS_ON_FIELD_NUMBER: _ClassVar[int]
    IS_APPLIED_FIELD_NUMBER: _ClassVar[int]
    STEP_TYPE_FIELD_NUMBER: _ClassVar[int]
    id: str
    config: StepConfig
    depends_on: _containers.RepeatedScalarFieldContainer[str]
    is_applied: bool
    step_type: _enums_pb2.StepType
    def __init__(self, id: _Optional[str] = ..., config: _Optional[_Union[StepConfig, _Mapping]] = ..., depends_on: _Optional[_Iterable[str]] = ..., is_applied: _Optional[bool] = ..., step_type: _Optional[_Union[_enums_pb2.StepType, str]] = ...) -> None: ...

class AnalysisPipelineIcebergOutput(_message.Message):
    __slots__ = ("namespace", "table_name", "branch")
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    TABLE_NAME_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    namespace: str
    table_name: str
    branch: str
    def __init__(self, namespace: _Optional[str] = ..., table_name: _Optional[str] = ..., branch: _Optional[str] = ...) -> None: ...

class AnalysisPipelineOutputNotification(_message.Message):
    __slots__ = ("method", "recipient", "subject_template", "body_template", "subscriber_ids", "excluded_recipients")
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    BODY_TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    SUBSCRIBER_IDS_FIELD_NUMBER: _ClassVar[int]
    EXCLUDED_RECIPIENTS_FIELD_NUMBER: _ClassVar[int]
    method: _enums_pb2.NotificationMethod
    recipient: str
    subject_template: str
    body_template: str
    subscriber_ids: _containers.RepeatedScalarFieldContainer[str]
    excluded_recipients: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, method: _Optional[_Union[_enums_pb2.NotificationMethod, str]] = ..., recipient: _Optional[str] = ..., subject_template: _Optional[str] = ..., body_template: _Optional[str] = ..., subscriber_ids: _Optional[_Iterable[str]] = ..., excluded_recipients: _Optional[_Iterable[str]] = ...) -> None: ...

class AnalysisPipelineOutput(_message.Message):
    __slots__ = ("result_id", "filename", "format", "options", "datasource_type", "build_mode", "iceberg", "notification", "build_timeout_warning_ms")
    RESULT_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    BUILD_MODE_FIELD_NUMBER: _ClassVar[int]
    ICEBERG_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    BUILD_TIMEOUT_WARNING_MS_FIELD_NUMBER: _ClassVar[int]
    result_id: str
    filename: str
    format: _enums_pb2.ExportFormat
    options: _struct_pb2.Struct
    datasource_type: _enums_pb2.DataSourceType
    build_mode: _enums_pb2.BuildMode
    iceberg: AnalysisPipelineIcebergOutput
    notification: AnalysisPipelineOutputNotification
    build_timeout_warning_ms: int
    def __init__(self, result_id: _Optional[str] = ..., filename: _Optional[str] = ..., format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., options: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., datasource_type: _Optional[_Union[_enums_pb2.DataSourceType, str]] = ..., build_mode: _Optional[_Union[_enums_pb2.BuildMode, str]] = ..., iceberg: _Optional[_Union[AnalysisPipelineIcebergOutput, _Mapping]] = ..., notification: _Optional[_Union[AnalysisPipelineOutputNotification, _Mapping]] = ..., build_timeout_warning_ms: _Optional[int] = ...) -> None: ...

class AnalysisPipelineTab(_message.Message):
    __slots__ = ("id", "name", "datasource", "output", "steps")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    datasource: AnalysisPipelineDatasource
    output: AnalysisPipelineOutput
    steps: _containers.RepeatedCompositeFieldContainer[AnalysisPipelineStep]
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., datasource: _Optional[_Union[AnalysisPipelineDatasource, _Mapping]] = ..., output: _Optional[_Union[AnalysisPipelineOutput, _Mapping]] = ..., steps: _Optional[_Iterable[_Union[AnalysisPipelineStep, _Mapping]]] = ...) -> None: ...

class AnalysisPipelinePayload(_message.Message):
    __slots__ = ("analysis_id", "tabs")
    ANALYSIS_ID_FIELD_NUMBER: _ClassVar[int]
    TABS_FIELD_NUMBER: _ClassVar[int]
    analysis_id: str
    tabs: _containers.RepeatedCompositeFieldContainer[AnalysisPipelineTab]
    def __init__(self, analysis_id: _Optional[str] = ..., tabs: _Optional[_Iterable[_Union[AnalysisPipelineTab, _Mapping]]] = ...) -> None: ...

class StringList(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, values: _Optional[_Iterable[str]] = ...) -> None: ...

class NumericList(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, values: _Optional[_Iterable[float]] = ...) -> None: ...

class SelectConfig(_message.Message):
    __slots__ = ("columns", "cast_map")
    class CastMapEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    CAST_MAP_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    cast_map: _containers.ScalarMap[str, str]
    def __init__(self, columns: _Optional[_Iterable[str]] = ..., cast_map: _Optional[_Mapping[str, str]] = ...) -> None: ...

class DropConfig(_message.Message):
    __slots__ = ("columns",)
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, columns: _Optional[_Iterable[str]] = ...) -> None: ...

class FilterValue(_message.Message):
    __slots__ = ("string_value", "number_value", "bool_value", "string_values")
    STRING_VALUE_FIELD_NUMBER: _ClassVar[int]
    NUMBER_VALUE_FIELD_NUMBER: _ClassVar[int]
    BOOL_VALUE_FIELD_NUMBER: _ClassVar[int]
    STRING_VALUES_FIELD_NUMBER: _ClassVar[int]
    string_value: str
    number_value: float
    bool_value: bool
    string_values: StringList
    def __init__(self, string_value: _Optional[str] = ..., number_value: _Optional[float] = ..., bool_value: _Optional[bool] = ..., string_values: _Optional[_Union[StringList, _Mapping]] = ...) -> None: ...

class FilterCondition(_message.Message):
    __slots__ = ("column", "operator", "value", "value_type", "compare_column")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    OPERATOR_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    VALUE_TYPE_FIELD_NUMBER: _ClassVar[int]
    COMPARE_COLUMN_FIELD_NUMBER: _ClassVar[int]
    column: str
    operator: _enums_pb2.FilterOperator
    value: FilterValue
    value_type: _enums_pb2.FilterValueType
    compare_column: str
    def __init__(self, column: _Optional[str] = ..., operator: _Optional[_Union[_enums_pb2.FilterOperator, str]] = ..., value: _Optional[_Union[FilterValue, _Mapping]] = ..., value_type: _Optional[_Union[_enums_pb2.FilterValueType, str]] = ..., compare_column: _Optional[str] = ...) -> None: ...

class FilterConfig(_message.Message):
    __slots__ = ("conditions", "logic")
    CONDITIONS_FIELD_NUMBER: _ClassVar[int]
    LOGIC_FIELD_NUMBER: _ClassVar[int]
    conditions: _containers.RepeatedCompositeFieldContainer[FilterCondition]
    logic: _enums_pb2.FilterLogic
    def __init__(self, conditions: _Optional[_Iterable[_Union[FilterCondition, _Mapping]]] = ..., logic: _Optional[_Union[_enums_pb2.FilterLogic, str]] = ...) -> None: ...

class Aggregation(_message.Message):
    __slots__ = ("column", "function", "alias")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    FUNCTION_FIELD_NUMBER: _ClassVar[int]
    ALIAS_FIELD_NUMBER: _ClassVar[int]
    column: str
    function: _enums_pb2.GroupByAggregationFunction
    alias: str
    def __init__(self, column: _Optional[str] = ..., function: _Optional[_Union[_enums_pb2.GroupByAggregationFunction, str]] = ..., alias: _Optional[str] = ...) -> None: ...

class GroupByConfig(_message.Message):
    __slots__ = ("group_by", "aggregations")
    GROUP_BY_FIELD_NUMBER: _ClassVar[int]
    AGGREGATIONS_FIELD_NUMBER: _ClassVar[int]
    group_by: _containers.RepeatedScalarFieldContainer[str]
    aggregations: _containers.RepeatedCompositeFieldContainer[Aggregation]
    def __init__(self, group_by: _Optional[_Iterable[str]] = ..., aggregations: _Optional[_Iterable[_Union[Aggregation, _Mapping]]] = ...) -> None: ...

class SortConfig(_message.Message):
    __slots__ = ("columns", "descending", "descending_all")
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    DESCENDING_FIELD_NUMBER: _ClassVar[int]
    DESCENDING_ALL_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    descending: _containers.RepeatedScalarFieldContainer[bool]
    descending_all: bool
    def __init__(self, columns: _Optional[_Iterable[str]] = ..., descending: _Optional[_Iterable[bool]] = ..., descending_all: _Optional[bool] = ...) -> None: ...

class RenameConfig(_message.Message):
    __slots__ = ("column_mapping",)
    class ColumnMappingEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    COLUMN_MAPPING_FIELD_NUMBER: _ClassVar[int]
    column_mapping: _containers.ScalarMap[str, str]
    def __init__(self, column_mapping: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ExpressionConfig(_message.Message):
    __slots__ = ("expression", "column_name")
    EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    COLUMN_NAME_FIELD_NUMBER: _ClassVar[int]
    expression: str
    column_name: str
    def __init__(self, expression: _Optional[str] = ..., column_name: _Optional[str] = ...) -> None: ...

class WithColumnsExpr(_message.Message):
    __slots__ = ("name", "type", "value", "column", "args", "code", "udf_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    UDF_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    type: _enums_pb2.WithColumnsExprType
    value: FilterValue
    column: str
    args: _containers.RepeatedScalarFieldContainer[str]
    code: str
    udf_id: str
    def __init__(self, name: _Optional[str] = ..., type: _Optional[_Union[_enums_pb2.WithColumnsExprType, str]] = ..., value: _Optional[_Union[FilterValue, _Mapping]] = ..., column: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ..., code: _Optional[str] = ..., udf_id: _Optional[str] = ...) -> None: ...

class WithColumnsConfig(_message.Message):
    __slots__ = ("expressions",)
    EXPRESSIONS_FIELD_NUMBER: _ClassVar[int]
    expressions: _containers.RepeatedCompositeFieldContainer[WithColumnsExpr]
    def __init__(self, expressions: _Optional[_Iterable[_Union[WithColumnsExpr, _Mapping]]] = ...) -> None: ...

class LimitConfig(_message.Message):
    __slots__ = ("n",)
    N_FIELD_NUMBER: _ClassVar[int]
    n: int
    def __init__(self, n: _Optional[int] = ...) -> None: ...

class SampleConfig(_message.Message):
    __slots__ = ("fraction", "seed")
    FRACTION_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    fraction: float
    seed: int
    def __init__(self, fraction: _Optional[float] = ..., seed: _Optional[int] = ...) -> None: ...

class TopKConfig(_message.Message):
    __slots__ = ("column", "k", "descending")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    K_FIELD_NUMBER: _ClassVar[int]
    DESCENDING_FIELD_NUMBER: _ClassVar[int]
    column: str
    k: int
    descending: bool
    def __init__(self, column: _Optional[str] = ..., k: _Optional[int] = ..., descending: _Optional[bool] = ...) -> None: ...

class DeduplicateConfig(_message.Message):
    __slots__ = ("subset", "keep")
    SUBSET_FIELD_NUMBER: _ClassVar[int]
    KEEP_FIELD_NUMBER: _ClassVar[int]
    subset: _containers.RepeatedScalarFieldContainer[str]
    keep: _enums_pb2.DeduplicateKeep
    def __init__(self, subset: _Optional[_Iterable[str]] = ..., keep: _Optional[_Union[_enums_pb2.DeduplicateKeep, str]] = ...) -> None: ...

class FillNullConfig(_message.Message):
    __slots__ = ("strategy", "columns", "value", "value_type")
    STRATEGY_FIELD_NUMBER: _ClassVar[int]
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    VALUE_TYPE_FIELD_NUMBER: _ClassVar[int]
    strategy: _enums_pb2.FillNullStrategy
    columns: _containers.RepeatedScalarFieldContainer[str]
    value: FilterValue
    value_type: str
    def __init__(self, strategy: _Optional[_Union[_enums_pb2.FillNullStrategy, str]] = ..., columns: _Optional[_Iterable[str]] = ..., value: _Optional[_Union[FilterValue, _Mapping]] = ..., value_type: _Optional[str] = ...) -> None: ...

class UnpivotConfig(_message.Message):
    __slots__ = ("id_vars", "value_vars", "variable_name", "value_name")
    ID_VARS_FIELD_NUMBER: _ClassVar[int]
    VALUE_VARS_FIELD_NUMBER: _ClassVar[int]
    VARIABLE_NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_NAME_FIELD_NUMBER: _ClassVar[int]
    id_vars: _containers.RepeatedScalarFieldContainer[str]
    value_vars: _containers.RepeatedScalarFieldContainer[str]
    variable_name: str
    value_name: str
    def __init__(self, id_vars: _Optional[_Iterable[str]] = ..., value_vars: _Optional[_Iterable[str]] = ..., variable_name: _Optional[str] = ..., value_name: _Optional[str] = ...) -> None: ...

class ExplodeConfig(_message.Message):
    __slots__ = ("columns",)
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, columns: _Optional[_Iterable[str]] = ...) -> None: ...

class PivotConfig(_message.Message):
    __slots__ = ("index", "columns", "aggregate_function", "value_columns")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    AGGREGATE_FUNCTION_FIELD_NUMBER: _ClassVar[int]
    VALUE_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    index: _containers.RepeatedScalarFieldContainer[str]
    columns: str
    aggregate_function: _enums_pb2.PivotAggregateFunction
    value_columns: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, index: _Optional[_Iterable[str]] = ..., columns: _Optional[str] = ..., aggregate_function: _Optional[_Union[_enums_pb2.PivotAggregateFunction, str]] = ..., value_columns: _Optional[_Iterable[str]] = ...) -> None: ...

class UnionByNameConfig(_message.Message):
    __slots__ = ("sources", "allow_missing")
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    ALLOW_MISSING_FIELD_NUMBER: _ClassVar[int]
    sources: _containers.RepeatedScalarFieldContainer[str]
    allow_missing: bool
    def __init__(self, sources: _Optional[_Iterable[str]] = ..., allow_missing: _Optional[bool] = ...) -> None: ...

class JoinColumn(_message.Message):
    __slots__ = ("id", "left_column", "right_column")
    ID_FIELD_NUMBER: _ClassVar[int]
    LEFT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    RIGHT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    id: str
    left_column: str
    right_column: str
    def __init__(self, id: _Optional[str] = ..., left_column: _Optional[str] = ..., right_column: _Optional[str] = ...) -> None: ...

class JoinConfig(_message.Message):
    __slots__ = ("how", "right_source", "join_columns", "right_columns", "suffix")
    HOW_FIELD_NUMBER: _ClassVar[int]
    RIGHT_SOURCE_FIELD_NUMBER: _ClassVar[int]
    JOIN_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    RIGHT_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    SUFFIX_FIELD_NUMBER: _ClassVar[int]
    how: _enums_pb2.JoinHow
    right_source: str
    join_columns: _containers.RepeatedCompositeFieldContainer[JoinColumn]
    right_columns: _containers.RepeatedScalarFieldContainer[str]
    suffix: str
    def __init__(self, how: _Optional[_Union[_enums_pb2.JoinHow, str]] = ..., right_source: _Optional[str] = ..., join_columns: _Optional[_Iterable[_Union[JoinColumn, _Mapping]]] = ..., right_columns: _Optional[_Iterable[str]] = ..., suffix: _Optional[str] = ...) -> None: ...

class ViewConfig(_message.Message):
    __slots__ = ("row_limit",)
    ROW_LIMIT_FIELD_NUMBER: _ClassVar[int]
    row_limit: int
    def __init__(self, row_limit: _Optional[int] = ...) -> None: ...

class ExportConfig(_message.Message):
    __slots__ = ("format", "filename", "destination")
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_FIELD_NUMBER: _ClassVar[int]
    format: _enums_pb2.ExportFormat
    filename: str
    destination: _enums_pb2.ExportDestination
    def __init__(self, format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., filename: _Optional[str] = ..., destination: _Optional[_Union[_enums_pb2.ExportDestination, str]] = ...) -> None: ...

class DownloadConfig(_message.Message):
    __slots__ = ("format", "filename")
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    format: _enums_pb2.ExportFormat
    filename: str
    def __init__(self, format: _Optional[_Union[_enums_pb2.ExportFormat, str]] = ..., filename: _Optional[str] = ...) -> None: ...

class Overlay(_message.Message):
    __slots__ = ("chart_type", "y_column", "aggregation", "y_axis_position")
    CHART_TYPE_FIELD_NUMBER: _ClassVar[int]
    Y_COLUMN_FIELD_NUMBER: _ClassVar[int]
    AGGREGATION_FIELD_NUMBER: _ClassVar[int]
    Y_AXIS_POSITION_FIELD_NUMBER: _ClassVar[int]
    chart_type: _enums_pb2.OverlayChartType
    y_column: str
    aggregation: _enums_pb2.ChartAggregation
    y_axis_position: _enums_pb2.YAxisPosition
    def __init__(self, chart_type: _Optional[_Union[_enums_pb2.OverlayChartType, str]] = ..., y_column: _Optional[str] = ..., aggregation: _Optional[_Union[_enums_pb2.ChartAggregation, str]] = ..., y_axis_position: _Optional[_Union[_enums_pb2.YAxisPosition, str]] = ...) -> None: ...

class ReferenceLine(_message.Message):
    __slots__ = ("axis", "value", "label", "color")
    AXIS_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    COLOR_FIELD_NUMBER: _ClassVar[int]
    axis: _enums_pb2.ReferenceAxis
    value: float
    label: str
    color: str
    def __init__(self, axis: _Optional[_Union[_enums_pb2.ReferenceAxis, str]] = ..., value: _Optional[float] = ..., label: _Optional[str] = ..., color: _Optional[str] = ...) -> None: ...

class ChartConfig(_message.Message):
    __slots__ = ("chart_type", "x_column", "y_column", "bins", "aggregation", "group_column", "group_sort_by", "group_sort_order", "group_sort_column", "stack_mode", "area_opacity", "date_bucket", "date_ordinal", "pan_zoom_enabled", "selection_enabled", "area_selection_enabled", "sort_by", "sort_order", "sort_column", "x_axis_label", "y_axis_label", "y_axis_scale", "y_axis_min", "y_axis_max", "display_units", "decimal_places", "legend_position", "title", "series_colors", "overlays", "reference_lines", "chart_height", "chart_width")
    CHART_TYPE_FIELD_NUMBER: _ClassVar[int]
    X_COLUMN_FIELD_NUMBER: _ClassVar[int]
    Y_COLUMN_FIELD_NUMBER: _ClassVar[int]
    BINS_FIELD_NUMBER: _ClassVar[int]
    AGGREGATION_FIELD_NUMBER: _ClassVar[int]
    GROUP_COLUMN_FIELD_NUMBER: _ClassVar[int]
    GROUP_SORT_BY_FIELD_NUMBER: _ClassVar[int]
    GROUP_SORT_ORDER_FIELD_NUMBER: _ClassVar[int]
    GROUP_SORT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    STACK_MODE_FIELD_NUMBER: _ClassVar[int]
    AREA_OPACITY_FIELD_NUMBER: _ClassVar[int]
    DATE_BUCKET_FIELD_NUMBER: _ClassVar[int]
    DATE_ORDINAL_FIELD_NUMBER: _ClassVar[int]
    PAN_ZOOM_ENABLED_FIELD_NUMBER: _ClassVar[int]
    SELECTION_ENABLED_FIELD_NUMBER: _ClassVar[int]
    AREA_SELECTION_ENABLED_FIELD_NUMBER: _ClassVar[int]
    SORT_BY_FIELD_NUMBER: _ClassVar[int]
    SORT_ORDER_FIELD_NUMBER: _ClassVar[int]
    SORT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    X_AXIS_LABEL_FIELD_NUMBER: _ClassVar[int]
    Y_AXIS_LABEL_FIELD_NUMBER: _ClassVar[int]
    Y_AXIS_SCALE_FIELD_NUMBER: _ClassVar[int]
    Y_AXIS_MIN_FIELD_NUMBER: _ClassVar[int]
    Y_AXIS_MAX_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_UNITS_FIELD_NUMBER: _ClassVar[int]
    DECIMAL_PLACES_FIELD_NUMBER: _ClassVar[int]
    LEGEND_POSITION_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SERIES_COLORS_FIELD_NUMBER: _ClassVar[int]
    OVERLAYS_FIELD_NUMBER: _ClassVar[int]
    REFERENCE_LINES_FIELD_NUMBER: _ClassVar[int]
    CHART_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    CHART_WIDTH_FIELD_NUMBER: _ClassVar[int]
    chart_type: _enums_pb2.ChartType
    x_column: str
    y_column: str
    bins: int
    aggregation: _enums_pb2.ChartAggregation
    group_column: str
    group_sort_by: _enums_pb2.GroupSortBy
    group_sort_order: _enums_pb2.SortDirection
    group_sort_column: str
    stack_mode: _enums_pb2.StackMode
    area_opacity: float
    date_bucket: _enums_pb2.DateBucket
    date_ordinal: _enums_pb2.DateOrdinal
    pan_zoom_enabled: bool
    selection_enabled: bool
    area_selection_enabled: bool
    sort_by: _enums_pb2.SortBy
    sort_order: _enums_pb2.SortDirection
    sort_column: str
    x_axis_label: str
    y_axis_label: str
    y_axis_scale: _enums_pb2.AxisScale
    y_axis_min: float
    y_axis_max: float
    display_units: _enums_pb2.DisplayUnits
    decimal_places: int
    legend_position: _enums_pb2.LegendPosition
    title: str
    series_colors: _containers.RepeatedScalarFieldContainer[str]
    overlays: _containers.RepeatedCompositeFieldContainer[Overlay]
    reference_lines: _containers.RepeatedCompositeFieldContainer[ReferenceLine]
    chart_height: _enums_pb2.ChartHeight
    chart_width: _enums_pb2.ChartWidth
    def __init__(self, chart_type: _Optional[_Union[_enums_pb2.ChartType, str]] = ..., x_column: _Optional[str] = ..., y_column: _Optional[str] = ..., bins: _Optional[int] = ..., aggregation: _Optional[_Union[_enums_pb2.ChartAggregation, str]] = ..., group_column: _Optional[str] = ..., group_sort_by: _Optional[_Union[_enums_pb2.GroupSortBy, str]] = ..., group_sort_order: _Optional[_Union[_enums_pb2.SortDirection, str]] = ..., group_sort_column: _Optional[str] = ..., stack_mode: _Optional[_Union[_enums_pb2.StackMode, str]] = ..., area_opacity: _Optional[float] = ..., date_bucket: _Optional[_Union[_enums_pb2.DateBucket, str]] = ..., date_ordinal: _Optional[_Union[_enums_pb2.DateOrdinal, str]] = ..., pan_zoom_enabled: _Optional[bool] = ..., selection_enabled: _Optional[bool] = ..., area_selection_enabled: _Optional[bool] = ..., sort_by: _Optional[_Union[_enums_pb2.SortBy, str]] = ..., sort_order: _Optional[_Union[_enums_pb2.SortDirection, str]] = ..., sort_column: _Optional[str] = ..., x_axis_label: _Optional[str] = ..., y_axis_label: _Optional[str] = ..., y_axis_scale: _Optional[_Union[_enums_pb2.AxisScale, str]] = ..., y_axis_min: _Optional[float] = ..., y_axis_max: _Optional[float] = ..., display_units: _Optional[_Union[_enums_pb2.DisplayUnits, str]] = ..., decimal_places: _Optional[int] = ..., legend_position: _Optional[_Union[_enums_pb2.LegendPosition, str]] = ..., title: _Optional[str] = ..., series_colors: _Optional[_Iterable[str]] = ..., overlays: _Optional[_Iterable[_Union[Overlay, _Mapping]]] = ..., reference_lines: _Optional[_Iterable[_Union[ReferenceLine, _Mapping]]] = ..., chart_height: _Optional[_Union[_enums_pb2.ChartHeight, str]] = ..., chart_width: _Optional[_Union[_enums_pb2.ChartWidth, str]] = ...) -> None: ...

class NotificationConfig(_message.Message):
    __slots__ = ("method", "recipient", "subscriber_ids", "bot_token", "recipient_source", "recipient_column", "input_columns", "output_column", "message_template", "subject_template", "batch_size")
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_FIELD_NUMBER: _ClassVar[int]
    SUBSCRIBER_IDS_FIELD_NUMBER: _ClassVar[int]
    BOT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_SOURCE_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    INPUT_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
    method: _enums_pb2.NotificationMethod
    recipient: str
    subscriber_ids: _containers.RepeatedScalarFieldContainer[str]
    bot_token: str
    recipient_source: _enums_pb2.RecipientSource
    recipient_column: str
    input_columns: _containers.RepeatedScalarFieldContainer[str]
    output_column: str
    message_template: str
    subject_template: str
    batch_size: int
    def __init__(self, method: _Optional[_Union[_enums_pb2.NotificationMethod, str]] = ..., recipient: _Optional[str] = ..., subscriber_ids: _Optional[_Iterable[str]] = ..., bot_token: _Optional[str] = ..., recipient_source: _Optional[_Union[_enums_pb2.RecipientSource, str]] = ..., recipient_column: _Optional[str] = ..., input_columns: _Optional[_Iterable[str]] = ..., output_column: _Optional[str] = ..., message_template: _Optional[str] = ..., subject_template: _Optional[str] = ..., batch_size: _Optional[int] = ...) -> None: ...

class AIConfig(_message.Message):
    __slots__ = ("provider", "model", "input_columns", "output_column", "error_column", "prompt_template", "batch_size", "max_retries", "rate_limit_rpm", "endpoint_url", "api_key", "temperature", "max_tokens", "request_options")
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    INPUT_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_COLUMN_FIELD_NUMBER: _ClassVar[int]
    ERROR_COLUMN_FIELD_NUMBER: _ClassVar[int]
    PROMPT_TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
    MAX_RETRIES_FIELD_NUMBER: _ClassVar[int]
    RATE_LIMIT_RPM_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    REQUEST_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    provider: _enums_pb2.AIProvider
    model: str
    input_columns: _containers.RepeatedScalarFieldContainer[str]
    output_column: str
    error_column: str
    prompt_template: str
    batch_size: int
    max_retries: int
    rate_limit_rpm: int
    endpoint_url: str
    api_key: str
    temperature: float
    max_tokens: int
    request_options: _struct_pb2.Struct
    def __init__(self, provider: _Optional[_Union[_enums_pb2.AIProvider, str]] = ..., model: _Optional[str] = ..., input_columns: _Optional[_Iterable[str]] = ..., output_column: _Optional[str] = ..., error_column: _Optional[str] = ..., prompt_template: _Optional[str] = ..., batch_size: _Optional[int] = ..., max_retries: _Optional[int] = ..., rate_limit_rpm: _Optional[int] = ..., endpoint_url: _Optional[str] = ..., api_key: _Optional[str] = ..., temperature: _Optional[float] = ..., max_tokens: _Optional[int] = ..., request_options: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class DatasourceConfig(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class TimeSeriesConfig(_message.Message):
    __slots__ = ("column", "operation_type", "new_column", "component", "value", "unit", "direction", "column2")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    OPERATION_TYPE_FIELD_NUMBER: _ClassVar[int]
    NEW_COLUMN_FIELD_NUMBER: _ClassVar[int]
    COMPONENT_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    COLUMN2_FIELD_NUMBER: _ClassVar[int]
    column: str
    operation_type: _enums_pb2.TimeseriesOperationType
    new_column: str
    component: _enums_pb2.TimeComponent
    value: int
    unit: _enums_pb2.DurationUnit
    direction: _enums_pb2.TimeDirection
    column2: str
    def __init__(self, column: _Optional[str] = ..., operation_type: _Optional[_Union[_enums_pb2.TimeseriesOperationType, str]] = ..., new_column: _Optional[str] = ..., component: _Optional[_Union[_enums_pb2.TimeComponent, str]] = ..., value: _Optional[int] = ..., unit: _Optional[_Union[_enums_pb2.DurationUnit, str]] = ..., direction: _Optional[_Union[_enums_pb2.TimeDirection, str]] = ..., column2: _Optional[str] = ...) -> None: ...

class StringTransformConfig(_message.Message):
    __slots__ = ("column", "method", "new_column", "start", "end", "pattern", "replacement", "group_index", "delimiter", "index")
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    NEW_COLUMN_FIELD_NUMBER: _ClassVar[int]
    START_FIELD_NUMBER: _ClassVar[int]
    END_FIELD_NUMBER: _ClassVar[int]
    PATTERN_FIELD_NUMBER: _ClassVar[int]
    REPLACEMENT_FIELD_NUMBER: _ClassVar[int]
    GROUP_INDEX_FIELD_NUMBER: _ClassVar[int]
    DELIMITER_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    column: str
    method: _enums_pb2.StringTransformMethod
    new_column: str
    start: int
    end: int
    pattern: str
    replacement: str
    group_index: int
    delimiter: str
    index: int
    def __init__(self, column: _Optional[str] = ..., method: _Optional[_Union[_enums_pb2.StringTransformMethod, str]] = ..., new_column: _Optional[str] = ..., start: _Optional[int] = ..., end: _Optional[int] = ..., pattern: _Optional[str] = ..., replacement: _Optional[str] = ..., group_index: _Optional[int] = ..., delimiter: _Optional[str] = ..., index: _Optional[int] = ...) -> None: ...

class StepConfig(_message.Message):
    __slots__ = ("select", "drop", "filter", "groupby", "sort", "rename", "expression", "with_columns", "limit", "sample", "topk", "deduplicate", "fill_null", "unpivot", "explode", "pivot", "union_by_name", "join", "view", "export", "download", "chart", "notification", "ai", "datasource", "timeseries", "string_transform")
    SELECT_FIELD_NUMBER: _ClassVar[int]
    DROP_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    GROUPBY_FIELD_NUMBER: _ClassVar[int]
    SORT_FIELD_NUMBER: _ClassVar[int]
    RENAME_FIELD_NUMBER: _ClassVar[int]
    EXPRESSION_FIELD_NUMBER: _ClassVar[int]
    WITH_COLUMNS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_FIELD_NUMBER: _ClassVar[int]
    TOPK_FIELD_NUMBER: _ClassVar[int]
    DEDUPLICATE_FIELD_NUMBER: _ClassVar[int]
    FILL_NULL_FIELD_NUMBER: _ClassVar[int]
    UNPIVOT_FIELD_NUMBER: _ClassVar[int]
    EXPLODE_FIELD_NUMBER: _ClassVar[int]
    PIVOT_FIELD_NUMBER: _ClassVar[int]
    UNION_BY_NAME_FIELD_NUMBER: _ClassVar[int]
    JOIN_FIELD_NUMBER: _ClassVar[int]
    VIEW_FIELD_NUMBER: _ClassVar[int]
    EXPORT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_FIELD_NUMBER: _ClassVar[int]
    CHART_FIELD_NUMBER: _ClassVar[int]
    NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    AI_FIELD_NUMBER: _ClassVar[int]
    DATASOURCE_FIELD_NUMBER: _ClassVar[int]
    TIMESERIES_FIELD_NUMBER: _ClassVar[int]
    STRING_TRANSFORM_FIELD_NUMBER: _ClassVar[int]
    select: SelectConfig
    drop: DropConfig
    filter: FilterConfig
    groupby: GroupByConfig
    sort: SortConfig
    rename: RenameConfig
    expression: ExpressionConfig
    with_columns: WithColumnsConfig
    limit: LimitConfig
    sample: SampleConfig
    topk: TopKConfig
    deduplicate: DeduplicateConfig
    fill_null: FillNullConfig
    unpivot: UnpivotConfig
    explode: ExplodeConfig
    pivot: PivotConfig
    union_by_name: UnionByNameConfig
    join: JoinConfig
    view: ViewConfig
    export: ExportConfig
    download: DownloadConfig
    chart: ChartConfig
    notification: NotificationConfig
    ai: AIConfig
    datasource: DatasourceConfig
    timeseries: TimeSeriesConfig
    string_transform: StringTransformConfig
    def __init__(self, select: _Optional[_Union[SelectConfig, _Mapping]] = ..., drop: _Optional[_Union[DropConfig, _Mapping]] = ..., filter: _Optional[_Union[FilterConfig, _Mapping]] = ..., groupby: _Optional[_Union[GroupByConfig, _Mapping]] = ..., sort: _Optional[_Union[SortConfig, _Mapping]] = ..., rename: _Optional[_Union[RenameConfig, _Mapping]] = ..., expression: _Optional[_Union[ExpressionConfig, _Mapping]] = ..., with_columns: _Optional[_Union[WithColumnsConfig, _Mapping]] = ..., limit: _Optional[_Union[LimitConfig, _Mapping]] = ..., sample: _Optional[_Union[SampleConfig, _Mapping]] = ..., topk: _Optional[_Union[TopKConfig, _Mapping]] = ..., deduplicate: _Optional[_Union[DeduplicateConfig, _Mapping]] = ..., fill_null: _Optional[_Union[FillNullConfig, _Mapping]] = ..., unpivot: _Optional[_Union[UnpivotConfig, _Mapping]] = ..., explode: _Optional[_Union[ExplodeConfig, _Mapping]] = ..., pivot: _Optional[_Union[PivotConfig, _Mapping]] = ..., union_by_name: _Optional[_Union[UnionByNameConfig, _Mapping]] = ..., join: _Optional[_Union[JoinConfig, _Mapping]] = ..., view: _Optional[_Union[ViewConfig, _Mapping]] = ..., export: _Optional[_Union[ExportConfig, _Mapping]] = ..., download: _Optional[_Union[DownloadConfig, _Mapping]] = ..., chart: _Optional[_Union[ChartConfig, _Mapping]] = ..., notification: _Optional[_Union[NotificationConfig, _Mapping]] = ..., ai: _Optional[_Union[AIConfig, _Mapping]] = ..., datasource: _Optional[_Union[DatasourceConfig, _Mapping]] = ..., timeseries: _Optional[_Union[TimeSeriesConfig, _Mapping]] = ..., string_transform: _Optional[_Union[StringTransformConfig, _Mapping]] = ...) -> None: ...
