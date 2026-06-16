from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from typing import ClassVar as _ClassVar

DESCRIPTOR: _descriptor.FileDescriptor

class AnalysisStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ANALYSIS_STATUS_UNSPECIFIED: _ClassVar[AnalysisStatus]
    ANALYSIS_STATUS_DRAFT: _ClassVar[AnalysisStatus]
    ANALYSIS_STATUS_RUNNING: _ClassVar[AnalysisStatus]
    ANALYSIS_STATUS_COMPLETED: _ClassVar[AnalysisStatus]
    ANALYSIS_STATUS_ERROR: _ClassVar[AnalysisStatus]

class ChartType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHART_TYPE_UNSPECIFIED: _ClassVar[ChartType]
    CHART_TYPE_BAR: _ClassVar[ChartType]
    CHART_TYPE_HORIZONTAL_BAR: _ClassVar[ChartType]
    CHART_TYPE_AREA: _ClassVar[ChartType]
    CHART_TYPE_HEATGRID: _ClassVar[ChartType]
    CHART_TYPE_HISTOGRAM: _ClassVar[ChartType]
    CHART_TYPE_SCATTER: _ClassVar[ChartType]
    CHART_TYPE_LINE: _ClassVar[ChartType]
    CHART_TYPE_PIE: _ClassVar[ChartType]
    CHART_TYPE_BOXPLOT: _ClassVar[ChartType]

class BuildJobStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_JOB_STATUS_UNSPECIFIED: _ClassVar[BuildJobStatus]
    BUILD_JOB_STATUS_QUEUED: _ClassVar[BuildJobStatus]
    BUILD_JOB_STATUS_LEASED: _ClassVar[BuildJobStatus]
    BUILD_JOB_STATUS_RUNNING: _ClassVar[BuildJobStatus]
    BUILD_JOB_STATUS_COMPLETED: _ClassVar[BuildJobStatus]
    BUILD_JOB_STATUS_FAILED: _ClassVar[BuildJobStatus]
    BUILD_JOB_STATUS_CANCELLED: _ClassVar[BuildJobStatus]

class BuildRunStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_RUN_STATUS_UNSPECIFIED: _ClassVar[BuildRunStatus]
    BUILD_RUN_STATUS_QUEUED: _ClassVar[BuildRunStatus]
    BUILD_RUN_STATUS_RUNNING: _ClassVar[BuildRunStatus]
    BUILD_RUN_STATUS_COMPLETED: _ClassVar[BuildRunStatus]
    BUILD_RUN_STATUS_FAILED: _ClassVar[BuildRunStatus]
    BUILD_RUN_STATUS_CANCELLED: _ClassVar[BuildRunStatus]
    BUILD_RUN_STATUS_ORPHANED: _ClassVar[BuildRunStatus]

class EngineStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_STATUS_UNSPECIFIED: _ClassVar[EngineStatus]
    ENGINE_STATUS_HEALTHY: _ClassVar[EngineStatus]
    ENGINE_STATUS_TERMINATED: _ClassVar[EngineStatus]

class EngineScope(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_SCOPE_UNSPECIFIED: _ClassVar[EngineScope]
    ENGINE_SCOPE_DATASOURCE_PREVIEW: _ClassVar[EngineScope]
    ENGINE_SCOPE_ANALYSIS_INTERACTIVE: _ClassVar[EngineScope]
    ENGINE_SCOPE_BUILD: _ClassVar[EngineScope]

class EngineReusePolicy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_REUSE_POLICY_UNSPECIFIED: _ClassVar[EngineReusePolicy]
    ENGINE_REUSE_POLICY_SHARED: _ClassVar[EngineReusePolicy]
    ENGINE_REUSE_POLICY_EXCLUSIVE: _ClassVar[EngineReusePolicy]

class ExportFormat(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EXPORT_FORMAT_UNSPECIFIED: _ClassVar[ExportFormat]
    EXPORT_FORMAT_CSV: _ClassVar[ExportFormat]
    EXPORT_FORMAT_PARQUET: _ClassVar[ExportFormat]
    EXPORT_FORMAT_JSON: _ClassVar[ExportFormat]
    EXPORT_FORMAT_NDJSON: _ClassVar[ExportFormat]
    EXPORT_FORMAT_DUCKDB: _ClassVar[ExportFormat]
    EXPORT_FORMAT_EXCEL: _ClassVar[ExportFormat]

class ExportDestination(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EXPORT_DESTINATION_UNSPECIFIED: _ClassVar[ExportDestination]
    EXPORT_DESTINATION_DOWNLOAD: _ClassVar[ExportDestination]
    EXPORT_DESTINATION_DATASOURCE: _ClassVar[ExportDestination]

class BuildStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_STATUS_UNSPECIFIED: _ClassVar[BuildStatus]
    BUILD_STATUS_SUCCESS: _ClassVar[BuildStatus]
    BUILD_STATUS_WARNING: _ClassVar[BuildStatus]

class BuildTabStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_TAB_STATUS_UNSPECIFIED: _ClassVar[BuildTabStatus]
    BUILD_TAB_STATUS_SUCCESS: _ClassVar[BuildTabStatus]
    BUILD_TAB_STATUS_FAILED: _ClassVar[BuildTabStatus]

class ComputeRunStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPUTE_RUN_STATUS_UNSPECIFIED: _ClassVar[ComputeRunStatus]
    COMPUTE_RUN_STATUS_SUCCESS: _ClassVar[ComputeRunStatus]
    COMPUTE_RUN_STATUS_FAILED: _ClassVar[ComputeRunStatus]

class ActiveBuildStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ACTIVE_BUILD_STATUS_UNSPECIFIED: _ClassVar[ActiveBuildStatus]
    ACTIVE_BUILD_STATUS_QUEUED: _ClassVar[ActiveBuildStatus]
    ACTIVE_BUILD_STATUS_RUNNING: _ClassVar[ActiveBuildStatus]
    ACTIVE_BUILD_STATUS_COMPLETED: _ClassVar[ActiveBuildStatus]
    ACTIVE_BUILD_STATUS_FAILED: _ClassVar[ActiveBuildStatus]
    ACTIVE_BUILD_STATUS_CANCELLED: _ClassVar[ActiveBuildStatus]

class BuildStepState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_STEP_STATE_UNSPECIFIED: _ClassVar[BuildStepState]
    BUILD_STEP_STATE_PENDING: _ClassVar[BuildStepState]
    BUILD_STEP_STATE_RUNNING: _ClassVar[BuildStepState]
    BUILD_STEP_STATE_COMPLETED: _ClassVar[BuildStepState]
    BUILD_STEP_STATE_FAILED: _ClassVar[BuildStepState]
    BUILD_STEP_STATE_SKIPPED: _ClassVar[BuildStepState]

class BuildLogLevel(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_LOG_LEVEL_UNSPECIFIED: _ClassVar[BuildLogLevel]
    BUILD_LOG_LEVEL_INFO: _ClassVar[BuildLogLevel]
    BUILD_LOG_LEVEL_WARNING: _ClassVar[BuildLogLevel]
    BUILD_LOG_LEVEL_ERROR: _ClassVar[BuildLogLevel]

class BuildEventType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BUILD_EVENT_TYPE_UNSPECIFIED: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_PLAN: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_STEP_START: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_STEP_COMPLETE: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_STEP_FAILED: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_PROGRESS: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_RESOURCES: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_LOG: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_COMPLETE: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_FAILED: _ClassVar[BuildEventType]
    BUILD_EVENT_TYPE_CANCELLED: _ClassVar[BuildEventType]

class ComputeRequestKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPUTE_REQUEST_KIND_UNSPECIFIED: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_PREVIEW: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_SCHEMA: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_ROW_COUNT: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_DOWNLOAD: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_EXPORT: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_INGEST_DATASOURCE: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_SPAWN_ENGINE: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE: _ClassVar[ComputeRequestKind]
    COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE: _ClassVar[ComputeRequestKind]

class ComputeRequestStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPUTE_REQUEST_STATUS_UNSPECIFIED: _ClassVar[ComputeRequestStatus]
    COMPUTE_REQUEST_STATUS_QUEUED: _ClassVar[ComputeRequestStatus]
    COMPUTE_REQUEST_STATUS_RUNNING: _ClassVar[ComputeRequestStatus]
    COMPUTE_REQUEST_STATUS_COMPLETED: _ClassVar[ComputeRequestStatus]
    COMPUTE_REQUEST_STATUS_FAILED: _ClassVar[ComputeRequestStatus]

class DataSourceCreatedBy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATA_SOURCE_CREATED_BY_UNSPECIFIED: _ClassVar[DataSourceCreatedBy]
    DATA_SOURCE_CREATED_BY_IMPORT: _ClassVar[DataSourceCreatedBy]
    DATA_SOURCE_CREATED_BY_ANALYSIS: _ClassVar[DataSourceCreatedBy]

class DataSourceTargetKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATA_SOURCE_TARGET_KIND_UNSPECIFIED: _ClassVar[DataSourceTargetKind]
    DATA_SOURCE_TARGET_KIND_ANALYSIS: _ClassVar[DataSourceTargetKind]
    DATA_SOURCE_TARGET_KIND_RAW: _ClassVar[DataSourceTargetKind]
    DATA_SOURCE_TARGET_KIND_DATASOURCE: _ClassVar[DataSourceTargetKind]

class DataSourceCategory(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATA_SOURCE_CATEGORY_UNSPECIFIED: _ClassVar[DataSourceCategory]
    DATA_SOURCE_CATEGORY_FILE: _ClassVar[DataSourceCategory]
    DATA_SOURCE_CATEGORY_DATABASE: _ClassVar[DataSourceCategory]
    DATA_SOURCE_CATEGORY_ANALYSIS: _ClassVar[DataSourceCategory]

class DataSourceFileType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATA_SOURCE_FILE_TYPE_UNSPECIFIED: _ClassVar[DataSourceFileType]
    DATA_SOURCE_FILE_TYPE_CSV: _ClassVar[DataSourceFileType]
    DATA_SOURCE_FILE_TYPE_PARQUET: _ClassVar[DataSourceFileType]
    DATA_SOURCE_FILE_TYPE_JSON: _ClassVar[DataSourceFileType]
    DATA_SOURCE_FILE_TYPE_NDJSON: _ClassVar[DataSourceFileType]
    DATA_SOURCE_FILE_TYPE_EXCEL: _ClassVar[DataSourceFileType]

class DataSourceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATA_SOURCE_TYPE_UNSPECIFIED: _ClassVar[DataSourceType]
    DATA_SOURCE_TYPE_FILE: _ClassVar[DataSourceType]
    DATA_SOURCE_TYPE_DATABASE: _ClassVar[DataSourceType]
    DATA_SOURCE_TYPE_ICEBERG: _ClassVar[DataSourceType]
    DATA_SOURCE_TYPE_ANALYSIS: _ClassVar[DataSourceType]

class EngineInstanceStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_INSTANCE_STATUS_UNSPECIFIED: _ClassVar[EngineInstanceStatus]
    ENGINE_INSTANCE_STATUS_STARTING: _ClassVar[EngineInstanceStatus]
    ENGINE_INSTANCE_STATUS_IDLE: _ClassVar[EngineInstanceStatus]
    ENGINE_INSTANCE_STATUS_RUNNING: _ClassVar[EngineInstanceStatus]
    ENGINE_INSTANCE_STATUS_STOPPING: _ClassVar[EngineInstanceStatus]
    ENGINE_INSTANCE_STATUS_STOPPED: _ClassVar[EngineInstanceStatus]
    ENGINE_INSTANCE_STATUS_FAILED: _ClassVar[EngineInstanceStatus]

class EngineRunKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_RUN_KIND_UNSPECIFIED: _ClassVar[EngineRunKind]
    ENGINE_RUN_KIND_BUILD: _ClassVar[EngineRunKind]
    ENGINE_RUN_KIND_PREVIEW: _ClassVar[EngineRunKind]
    ENGINE_RUN_KIND_ROW_COUNT: _ClassVar[EngineRunKind]
    ENGINE_RUN_KIND_DOWNLOAD: _ClassVar[EngineRunKind]
    ENGINE_RUN_KIND_INGEST: _ClassVar[EngineRunKind]

class EngineRunStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_RUN_STATUS_UNSPECIFIED: _ClassVar[EngineRunStatus]
    ENGINE_RUN_STATUS_RUNNING: _ClassVar[EngineRunStatus]
    ENGINE_RUN_STATUS_SUCCESS: _ClassVar[EngineRunStatus]
    ENGINE_RUN_STATUS_FAILED: _ClassVar[EngineRunStatus]
    ENGINE_RUN_STATUS_CANCELLED: _ClassVar[EngineRunStatus]

class EngineRunExecutionCategory(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_RUN_EXECUTION_CATEGORY_UNSPECIFIED: _ClassVar[EngineRunExecutionCategory]
    ENGINE_RUN_EXECUTION_CATEGORY_READ: _ClassVar[EngineRunExecutionCategory]
    ENGINE_RUN_EXECUTION_CATEGORY_STEP: _ClassVar[EngineRunExecutionCategory]
    ENGINE_RUN_EXECUTION_CATEGORY_PLAN: _ClassVar[EngineRunExecutionCategory]
    ENGINE_RUN_EXECUTION_CATEGORY_COMPUTE: _ClassVar[EngineRunExecutionCategory]
    ENGINE_RUN_EXECUTION_CATEGORY_WRITE: _ClassVar[EngineRunExecutionCategory]

class SchemaDiffStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SCHEMA_DIFF_STATUS_UNSPECIFIED: _ClassVar[SchemaDiffStatus]
    SCHEMA_DIFF_STATUS_ADDED: _ClassVar[SchemaDiffStatus]
    SCHEMA_DIFF_STATUS_REMOVED: _ClassVar[SchemaDiffStatus]
    SCHEMA_DIFF_STATUS_TYPE_CHANGED: _ClassVar[SchemaDiffStatus]

class HealthCheckType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    HEALTH_CHECK_TYPE_UNSPECIFIED: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_ROW_COUNT: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_COLUMN_NULL: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_COLUMN_UNIQUE: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_COLUMN_RANGE: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_COLUMN_COUNT: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_NULL_PERCENTAGE: _ClassVar[HealthCheckType]
    HEALTH_CHECK_TYPE_DUPLICATE_PERCENTAGE: _ClassVar[HealthCheckType]

class RuntimePayloadKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RUNTIME_PAYLOAD_KIND_UNSPECIFIED: _ClassVar[RuntimePayloadKind]
    RUNTIME_PAYLOAD_KIND_BUILD: _ClassVar[RuntimePayloadKind]
    RUNTIME_PAYLOAD_KIND_ENGINE: _ClassVar[RuntimePayloadKind]
    RUNTIME_PAYLOAD_KIND_JOB: _ClassVar[RuntimePayloadKind]
    RUNTIME_PAYLOAD_KIND_COMPUTE_REQUEST: _ClassVar[RuntimePayloadKind]
    RUNTIME_PAYLOAD_KIND_COMPUTE_RESPONSE: _ClassVar[RuntimePayloadKind]

class RuntimeWorkerKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RUNTIME_WORKER_KIND_UNSPECIFIED: _ClassVar[RuntimeWorkerKind]
    RUNTIME_WORKER_KIND_API: _ClassVar[RuntimeWorkerKind]
    RUNTIME_WORKER_KIND_BUILD_MANAGER: _ClassVar[RuntimeWorkerKind]
    RUNTIME_WORKER_KIND_BUILD_WORKER: _ClassVar[RuntimeWorkerKind]
    RUNTIME_WORKER_KIND_SCHEDULER: _ClassVar[RuntimeWorkerKind]

class FilterValueType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILTER_VALUE_TYPE_UNSPECIFIED: _ClassVar[FilterValueType]
    FILTER_VALUE_TYPE_STRING: _ClassVar[FilterValueType]
    FILTER_VALUE_TYPE_NUMBER: _ClassVar[FilterValueType]
    FILTER_VALUE_TYPE_DATE: _ClassVar[FilterValueType]
    FILTER_VALUE_TYPE_DATETIME: _ClassVar[FilterValueType]
    FILTER_VALUE_TYPE_COLUMN: _ClassVar[FilterValueType]
    FILTER_VALUE_TYPE_BOOLEAN: _ClassVar[FilterValueType]

class FilterLogic(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILTER_LOGIC_UNSPECIFIED: _ClassVar[FilterLogic]
    FILTER_LOGIC_AND: _ClassVar[FilterLogic]
    FILTER_LOGIC_OR: _ClassVar[FilterLogic]

class FilterOperator(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILTER_OPERATOR_UNSPECIFIED: _ClassVar[FilterOperator]
    FILTER_OPERATOR_EQUAL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_DOUBLE_EQUAL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_NOT_EQUAL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_GREATER_THAN: _ClassVar[FilterOperator]
    FILTER_OPERATOR_LESS_THAN: _ClassVar[FilterOperator]
    FILTER_OPERATOR_GREATER_EQUAL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_LESS_EQUAL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_CONTAINS: _ClassVar[FilterOperator]
    FILTER_OPERATOR_NOT_CONTAINS: _ClassVar[FilterOperator]
    FILTER_OPERATOR_STARTS_WITH: _ClassVar[FilterOperator]
    FILTER_OPERATOR_ENDS_WITH: _ClassVar[FilterOperator]
    FILTER_OPERATOR_REGEX: _ClassVar[FilterOperator]
    FILTER_OPERATOR_IS_NULL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_IS_NOT_NULL: _ClassVar[FilterOperator]
    FILTER_OPERATOR_IN: _ClassVar[FilterOperator]
    FILTER_OPERATOR_NOT_IN: _ClassVar[FilterOperator]

class StringTransformMethod(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STRING_TRANSFORM_METHOD_UNSPECIFIED: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_UPPERCASE: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_LOWERCASE: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_TITLE: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_STRIP: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_LSTRIP: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_RSTRIP: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_LENGTH: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_SLICE: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_REPLACE: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_EXTRACT: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_SPLIT: _ClassVar[StringTransformMethod]
    STRING_TRANSFORM_METHOD_SPLIT_TAKE: _ClassVar[StringTransformMethod]

class TimeseriesOperationType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TIMESERIES_OPERATION_TYPE_UNSPECIFIED: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_EXTRACT: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_TIMESTAMP: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_ADD: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_SUBTRACT: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_OFFSET: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_DIFF: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_TRUNCATE: _ClassVar[TimeseriesOperationType]
    TIMESERIES_OPERATION_TYPE_ROUND: _ClassVar[TimeseriesOperationType]

class TimeComponent(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TIME_COMPONENT_UNSPECIFIED: _ClassVar[TimeComponent]
    TIME_COMPONENT_YEAR: _ClassVar[TimeComponent]
    TIME_COMPONENT_MONTH: _ClassVar[TimeComponent]
    TIME_COMPONENT_DAY: _ClassVar[TimeComponent]
    TIME_COMPONENT_HOUR: _ClassVar[TimeComponent]
    TIME_COMPONENT_MINUTE: _ClassVar[TimeComponent]
    TIME_COMPONENT_SECOND: _ClassVar[TimeComponent]
    TIME_COMPONENT_QUARTER: _ClassVar[TimeComponent]
    TIME_COMPONENT_WEEK: _ClassVar[TimeComponent]
    TIME_COMPONENT_DAYOFWEEK: _ClassVar[TimeComponent]

class DurationUnit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DURATION_UNIT_UNSPECIFIED: _ClassVar[DurationUnit]
    DURATION_UNIT_SECONDS: _ClassVar[DurationUnit]
    DURATION_UNIT_MINUTES: _ClassVar[DurationUnit]
    DURATION_UNIT_HOURS: _ClassVar[DurationUnit]
    DURATION_UNIT_DAYS: _ClassVar[DurationUnit]
    DURATION_UNIT_WEEKS: _ClassVar[DurationUnit]
    DURATION_UNIT_MONTHS: _ClassVar[DurationUnit]

class TimeDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    TIME_DIRECTION_UNSPECIFIED: _ClassVar[TimeDirection]
    TIME_DIRECTION_ADD: _ClassVar[TimeDirection]
    TIME_DIRECTION_SUBTRACT: _ClassVar[TimeDirection]

class WithColumnsExprType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WITH_COLUMNS_EXPR_TYPE_UNSPECIFIED: _ClassVar[WithColumnsExprType]
    WITH_COLUMNS_EXPR_TYPE_LITERAL: _ClassVar[WithColumnsExprType]
    WITH_COLUMNS_EXPR_TYPE_COLUMN: _ClassVar[WithColumnsExprType]
    WITH_COLUMNS_EXPR_TYPE_UDF: _ClassVar[WithColumnsExprType]

class NotificationMethod(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NOTIFICATION_METHOD_UNSPECIFIED: _ClassVar[NotificationMethod]
    NOTIFICATION_METHOD_EMAIL: _ClassVar[NotificationMethod]
    NOTIFICATION_METHOD_TELEGRAM: _ClassVar[NotificationMethod]

class JoinHow(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    JOIN_HOW_UNSPECIFIED: _ClassVar[JoinHow]
    JOIN_HOW_INNER: _ClassVar[JoinHow]
    JOIN_HOW_LEFT: _ClassVar[JoinHow]
    JOIN_HOW_RIGHT: _ClassVar[JoinHow]
    JOIN_HOW_OUTER: _ClassVar[JoinHow]
    JOIN_HOW_CROSS: _ClassVar[JoinHow]

class GroupByAggregationFunction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GROUP_BY_AGGREGATION_FUNCTION_UNSPECIFIED: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_SUM: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_MEAN: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_COUNT: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_MIN: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_MAX: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_FIRST: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_LAST: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_MEDIAN: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_STD: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_N_UNIQUE: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_COLLECT_LIST: _ClassVar[GroupByAggregationFunction]
    GROUP_BY_AGGREGATION_FUNCTION_COLLECT_SET: _ClassVar[GroupByAggregationFunction]

class ChartAggregation(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHART_AGGREGATION_UNSPECIFIED: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_SUM: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_MEAN: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_COUNT: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_MIN: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_MAX: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_MEDIAN: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_STD: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_VARIANCE: _ClassVar[ChartAggregation]
    CHART_AGGREGATION_UNIQUE_COUNT: _ClassVar[ChartAggregation]

class OverlayChartType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OVERLAY_CHART_TYPE_UNSPECIFIED: _ClassVar[OverlayChartType]
    OVERLAY_CHART_TYPE_LINE: _ClassVar[OverlayChartType]
    OVERLAY_CHART_TYPE_AREA: _ClassVar[OverlayChartType]
    OVERLAY_CHART_TYPE_BAR: _ClassVar[OverlayChartType]
    OVERLAY_CHART_TYPE_SCATTER: _ClassVar[OverlayChartType]

class YAxisPosition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    Y_AXIS_POSITION_UNSPECIFIED: _ClassVar[YAxisPosition]
    Y_AXIS_POSITION_LEFT: _ClassVar[YAxisPosition]
    Y_AXIS_POSITION_RIGHT: _ClassVar[YAxisPosition]

class ReferenceAxis(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    REFERENCE_AXIS_UNSPECIFIED: _ClassVar[ReferenceAxis]
    REFERENCE_AXIS_X: _ClassVar[ReferenceAxis]
    REFERENCE_AXIS_Y: _ClassVar[ReferenceAxis]

class SortDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SORT_DIRECTION_UNSPECIFIED: _ClassVar[SortDirection]
    SORT_DIRECTION_ASC: _ClassVar[SortDirection]
    SORT_DIRECTION_DESC: _ClassVar[SortDirection]

class GroupSortBy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GROUP_SORT_BY_UNSPECIFIED: _ClassVar[GroupSortBy]
    GROUP_SORT_BY_NAME: _ClassVar[GroupSortBy]
    GROUP_SORT_BY_VALUE: _ClassVar[GroupSortBy]
    GROUP_SORT_BY_CUSTOM: _ClassVar[GroupSortBy]

class SortBy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SORT_BY_UNSPECIFIED: _ClassVar[SortBy]
    SORT_BY_X: _ClassVar[SortBy]
    SORT_BY_Y: _ClassVar[SortBy]
    SORT_BY_CUSTOM: _ClassVar[SortBy]

class StackMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STACK_MODE_UNSPECIFIED: _ClassVar[StackMode]
    STACK_MODE_GROUPED: _ClassVar[StackMode]
    STACK_MODE_STACKED: _ClassVar[StackMode]
    STACK_MODE_STACKED_100: _ClassVar[StackMode]

class DateBucket(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATE_BUCKET_UNSPECIFIED: _ClassVar[DateBucket]
    DATE_BUCKET_EXACT: _ClassVar[DateBucket]
    DATE_BUCKET_YEAR: _ClassVar[DateBucket]
    DATE_BUCKET_QUARTER: _ClassVar[DateBucket]
    DATE_BUCKET_MONTH: _ClassVar[DateBucket]
    DATE_BUCKET_WEEK: _ClassVar[DateBucket]
    DATE_BUCKET_DAY: _ClassVar[DateBucket]
    DATE_BUCKET_HOUR: _ClassVar[DateBucket]

class DateOrdinal(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DATE_ORDINAL_UNSPECIFIED: _ClassVar[DateOrdinal]
    DATE_ORDINAL_DAY_OF_WEEK: _ClassVar[DateOrdinal]
    DATE_ORDINAL_MONTH_OF_YEAR: _ClassVar[DateOrdinal]
    DATE_ORDINAL_QUARTER_OF_YEAR: _ClassVar[DateOrdinal]

class AxisScale(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AXIS_SCALE_UNSPECIFIED: _ClassVar[AxisScale]
    AXIS_SCALE_LINEAR: _ClassVar[AxisScale]
    AXIS_SCALE_LOG: _ClassVar[AxisScale]

class DisplayUnits(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DISPLAY_UNITS_UNSPECIFIED: _ClassVar[DisplayUnits]
    DISPLAY_UNITS_NONE: _ClassVar[DisplayUnits]
    DISPLAY_UNITS_THOUSANDS: _ClassVar[DisplayUnits]
    DISPLAY_UNITS_MILLIONS: _ClassVar[DisplayUnits]
    DISPLAY_UNITS_BILLIONS: _ClassVar[DisplayUnits]
    DISPLAY_UNITS_PERCENT: _ClassVar[DisplayUnits]

class LegendPosition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    LEGEND_POSITION_UNSPECIFIED: _ClassVar[LegendPosition]
    LEGEND_POSITION_TOP: _ClassVar[LegendPosition]
    LEGEND_POSITION_BOTTOM: _ClassVar[LegendPosition]
    LEGEND_POSITION_LEFT: _ClassVar[LegendPosition]
    LEGEND_POSITION_RIGHT: _ClassVar[LegendPosition]
    LEGEND_POSITION_NONE: _ClassVar[LegendPosition]

class ChartHeight(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHART_HEIGHT_UNSPECIFIED: _ClassVar[ChartHeight]
    CHART_HEIGHT_SMALL: _ClassVar[ChartHeight]
    CHART_HEIGHT_MEDIUM: _ClassVar[ChartHeight]
    CHART_HEIGHT_LARGE: _ClassVar[ChartHeight]
    CHART_HEIGHT_XLARGE: _ClassVar[ChartHeight]

class ChartWidth(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHART_WIDTH_UNSPECIFIED: _ClassVar[ChartWidth]
    CHART_WIDTH_NORMAL: _ClassVar[ChartWidth]
    CHART_WIDTH_WIDE: _ClassVar[ChartWidth]
    CHART_WIDTH_FULL: _ClassVar[ChartWidth]

class RecipientSource(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RECIPIENT_SOURCE_UNSPECIFIED: _ClassVar[RecipientSource]
    RECIPIENT_SOURCE_MANUAL: _ClassVar[RecipientSource]
    RECIPIENT_SOURCE_COLUMN: _ClassVar[RecipientSource]

class AIProvider(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AI_PROVIDER_UNSPECIFIED: _ClassVar[AIProvider]
    AI_PROVIDER_OLLAMA: _ClassVar[AIProvider]
    AI_PROVIDER_OPENAI: _ClassVar[AIProvider]
    AI_PROVIDER_OPENROUTER: _ClassVar[AIProvider]
    AI_PROVIDER_HUGGINGFACE: _ClassVar[AIProvider]

class DeduplicateKeep(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DEDUPLICATE_KEEP_UNSPECIFIED: _ClassVar[DeduplicateKeep]
    DEDUPLICATE_KEEP_FIRST: _ClassVar[DeduplicateKeep]
    DEDUPLICATE_KEEP_LAST: _ClassVar[DeduplicateKeep]
    DEDUPLICATE_KEEP_ANY: _ClassVar[DeduplicateKeep]
    DEDUPLICATE_KEEP_NONE: _ClassVar[DeduplicateKeep]

class PivotAggregateFunction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PIVOT_AGGREGATE_FUNCTION_UNSPECIFIED: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_FIRST: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_LAST: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_SUM: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_MEAN: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_MEDIAN: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_MIN: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_MAX: _ClassVar[PivotAggregateFunction]
    PIVOT_AGGREGATE_FUNCTION_COUNT: _ClassVar[PivotAggregateFunction]

class FillNullStrategy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILL_NULL_STRATEGY_UNSPECIFIED: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_FORWARD: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_BACKWARD: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_MEAN: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_MEDIAN: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_ZERO: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_LITERAL: _ClassVar[FillNullStrategy]
    FILL_NULL_STRATEGY_DROP_ROWS: _ClassVar[FillNullStrategy]
ANALYSIS_STATUS_UNSPECIFIED: AnalysisStatus
ANALYSIS_STATUS_DRAFT: AnalysisStatus
ANALYSIS_STATUS_RUNNING: AnalysisStatus
ANALYSIS_STATUS_COMPLETED: AnalysisStatus
ANALYSIS_STATUS_ERROR: AnalysisStatus
CHART_TYPE_UNSPECIFIED: ChartType
CHART_TYPE_BAR: ChartType
CHART_TYPE_HORIZONTAL_BAR: ChartType
CHART_TYPE_AREA: ChartType
CHART_TYPE_HEATGRID: ChartType
CHART_TYPE_HISTOGRAM: ChartType
CHART_TYPE_SCATTER: ChartType
CHART_TYPE_LINE: ChartType
CHART_TYPE_PIE: ChartType
CHART_TYPE_BOXPLOT: ChartType
BUILD_JOB_STATUS_UNSPECIFIED: BuildJobStatus
BUILD_JOB_STATUS_QUEUED: BuildJobStatus
BUILD_JOB_STATUS_LEASED: BuildJobStatus
BUILD_JOB_STATUS_RUNNING: BuildJobStatus
BUILD_JOB_STATUS_COMPLETED: BuildJobStatus
BUILD_JOB_STATUS_FAILED: BuildJobStatus
BUILD_JOB_STATUS_CANCELLED: BuildJobStatus
BUILD_RUN_STATUS_UNSPECIFIED: BuildRunStatus
BUILD_RUN_STATUS_QUEUED: BuildRunStatus
BUILD_RUN_STATUS_RUNNING: BuildRunStatus
BUILD_RUN_STATUS_COMPLETED: BuildRunStatus
BUILD_RUN_STATUS_FAILED: BuildRunStatus
BUILD_RUN_STATUS_CANCELLED: BuildRunStatus
BUILD_RUN_STATUS_ORPHANED: BuildRunStatus
ENGINE_STATUS_UNSPECIFIED: EngineStatus
ENGINE_STATUS_HEALTHY: EngineStatus
ENGINE_STATUS_TERMINATED: EngineStatus
ENGINE_SCOPE_UNSPECIFIED: EngineScope
ENGINE_SCOPE_DATASOURCE_PREVIEW: EngineScope
ENGINE_SCOPE_ANALYSIS_INTERACTIVE: EngineScope
ENGINE_SCOPE_BUILD: EngineScope
ENGINE_REUSE_POLICY_UNSPECIFIED: EngineReusePolicy
ENGINE_REUSE_POLICY_SHARED: EngineReusePolicy
ENGINE_REUSE_POLICY_EXCLUSIVE: EngineReusePolicy
EXPORT_FORMAT_UNSPECIFIED: ExportFormat
EXPORT_FORMAT_CSV: ExportFormat
EXPORT_FORMAT_PARQUET: ExportFormat
EXPORT_FORMAT_JSON: ExportFormat
EXPORT_FORMAT_NDJSON: ExportFormat
EXPORT_FORMAT_DUCKDB: ExportFormat
EXPORT_FORMAT_EXCEL: ExportFormat
EXPORT_DESTINATION_UNSPECIFIED: ExportDestination
EXPORT_DESTINATION_DOWNLOAD: ExportDestination
EXPORT_DESTINATION_DATASOURCE: ExportDestination
BUILD_STATUS_UNSPECIFIED: BuildStatus
BUILD_STATUS_SUCCESS: BuildStatus
BUILD_STATUS_WARNING: BuildStatus
BUILD_TAB_STATUS_UNSPECIFIED: BuildTabStatus
BUILD_TAB_STATUS_SUCCESS: BuildTabStatus
BUILD_TAB_STATUS_FAILED: BuildTabStatus
COMPUTE_RUN_STATUS_UNSPECIFIED: ComputeRunStatus
COMPUTE_RUN_STATUS_SUCCESS: ComputeRunStatus
COMPUTE_RUN_STATUS_FAILED: ComputeRunStatus
ACTIVE_BUILD_STATUS_UNSPECIFIED: ActiveBuildStatus
ACTIVE_BUILD_STATUS_QUEUED: ActiveBuildStatus
ACTIVE_BUILD_STATUS_RUNNING: ActiveBuildStatus
ACTIVE_BUILD_STATUS_COMPLETED: ActiveBuildStatus
ACTIVE_BUILD_STATUS_FAILED: ActiveBuildStatus
ACTIVE_BUILD_STATUS_CANCELLED: ActiveBuildStatus
BUILD_STEP_STATE_UNSPECIFIED: BuildStepState
BUILD_STEP_STATE_PENDING: BuildStepState
BUILD_STEP_STATE_RUNNING: BuildStepState
BUILD_STEP_STATE_COMPLETED: BuildStepState
BUILD_STEP_STATE_FAILED: BuildStepState
BUILD_STEP_STATE_SKIPPED: BuildStepState
BUILD_LOG_LEVEL_UNSPECIFIED: BuildLogLevel
BUILD_LOG_LEVEL_INFO: BuildLogLevel
BUILD_LOG_LEVEL_WARNING: BuildLogLevel
BUILD_LOG_LEVEL_ERROR: BuildLogLevel
BUILD_EVENT_TYPE_UNSPECIFIED: BuildEventType
BUILD_EVENT_TYPE_PLAN: BuildEventType
BUILD_EVENT_TYPE_STEP_START: BuildEventType
BUILD_EVENT_TYPE_STEP_COMPLETE: BuildEventType
BUILD_EVENT_TYPE_STEP_FAILED: BuildEventType
BUILD_EVENT_TYPE_PROGRESS: BuildEventType
BUILD_EVENT_TYPE_RESOURCES: BuildEventType
BUILD_EVENT_TYPE_LOG: BuildEventType
BUILD_EVENT_TYPE_COMPLETE: BuildEventType
BUILD_EVENT_TYPE_FAILED: BuildEventType
BUILD_EVENT_TYPE_CANCELLED: BuildEventType
COMPUTE_REQUEST_KIND_UNSPECIFIED: ComputeRequestKind
COMPUTE_REQUEST_KIND_PREVIEW: ComputeRequestKind
COMPUTE_REQUEST_KIND_SCHEMA: ComputeRequestKind
COMPUTE_REQUEST_KIND_ROW_COUNT: ComputeRequestKind
COMPUTE_REQUEST_KIND_DOWNLOAD: ComputeRequestKind
COMPUTE_REQUEST_KIND_EXPORT: ComputeRequestKind
COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE: ComputeRequestKind
COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE: ComputeRequestKind
COMPUTE_REQUEST_KIND_CREATE_ICEBERG_DATASOURCE: ComputeRequestKind
COMPUTE_REQUEST_KIND_INGEST_DATASOURCE: ComputeRequestKind
COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA: ComputeRequestKind
COMPUTE_REQUEST_KIND_DATASOURCE_COLUMN_STATS: ComputeRequestKind
COMPUTE_REQUEST_KIND_COMPARE_ICEBERG_SNAPSHOTS: ComputeRequestKind
COMPUTE_REQUEST_KIND_SPAWN_ENGINE: ComputeRequestKind
COMPUTE_REQUEST_KIND_CONFIGURE_ENGINE: ComputeRequestKind
COMPUTE_REQUEST_KIND_SHUTDOWN_ENGINE: ComputeRequestKind
COMPUTE_REQUEST_STATUS_UNSPECIFIED: ComputeRequestStatus
COMPUTE_REQUEST_STATUS_QUEUED: ComputeRequestStatus
COMPUTE_REQUEST_STATUS_RUNNING: ComputeRequestStatus
COMPUTE_REQUEST_STATUS_COMPLETED: ComputeRequestStatus
COMPUTE_REQUEST_STATUS_FAILED: ComputeRequestStatus
DATA_SOURCE_CREATED_BY_UNSPECIFIED: DataSourceCreatedBy
DATA_SOURCE_CREATED_BY_IMPORT: DataSourceCreatedBy
DATA_SOURCE_CREATED_BY_ANALYSIS: DataSourceCreatedBy
DATA_SOURCE_TARGET_KIND_UNSPECIFIED: DataSourceTargetKind
DATA_SOURCE_TARGET_KIND_ANALYSIS: DataSourceTargetKind
DATA_SOURCE_TARGET_KIND_RAW: DataSourceTargetKind
DATA_SOURCE_TARGET_KIND_DATASOURCE: DataSourceTargetKind
DATA_SOURCE_CATEGORY_UNSPECIFIED: DataSourceCategory
DATA_SOURCE_CATEGORY_FILE: DataSourceCategory
DATA_SOURCE_CATEGORY_DATABASE: DataSourceCategory
DATA_SOURCE_CATEGORY_ANALYSIS: DataSourceCategory
DATA_SOURCE_FILE_TYPE_UNSPECIFIED: DataSourceFileType
DATA_SOURCE_FILE_TYPE_CSV: DataSourceFileType
DATA_SOURCE_FILE_TYPE_PARQUET: DataSourceFileType
DATA_SOURCE_FILE_TYPE_JSON: DataSourceFileType
DATA_SOURCE_FILE_TYPE_NDJSON: DataSourceFileType
DATA_SOURCE_FILE_TYPE_EXCEL: DataSourceFileType
DATA_SOURCE_TYPE_UNSPECIFIED: DataSourceType
DATA_SOURCE_TYPE_FILE: DataSourceType
DATA_SOURCE_TYPE_DATABASE: DataSourceType
DATA_SOURCE_TYPE_ICEBERG: DataSourceType
DATA_SOURCE_TYPE_ANALYSIS: DataSourceType
ENGINE_INSTANCE_STATUS_UNSPECIFIED: EngineInstanceStatus
ENGINE_INSTANCE_STATUS_STARTING: EngineInstanceStatus
ENGINE_INSTANCE_STATUS_IDLE: EngineInstanceStatus
ENGINE_INSTANCE_STATUS_RUNNING: EngineInstanceStatus
ENGINE_INSTANCE_STATUS_STOPPING: EngineInstanceStatus
ENGINE_INSTANCE_STATUS_STOPPED: EngineInstanceStatus
ENGINE_INSTANCE_STATUS_FAILED: EngineInstanceStatus
ENGINE_RUN_KIND_UNSPECIFIED: EngineRunKind
ENGINE_RUN_KIND_BUILD: EngineRunKind
ENGINE_RUN_KIND_PREVIEW: EngineRunKind
ENGINE_RUN_KIND_ROW_COUNT: EngineRunKind
ENGINE_RUN_KIND_DOWNLOAD: EngineRunKind
ENGINE_RUN_KIND_INGEST: EngineRunKind
ENGINE_RUN_STATUS_UNSPECIFIED: EngineRunStatus
ENGINE_RUN_STATUS_RUNNING: EngineRunStatus
ENGINE_RUN_STATUS_SUCCESS: EngineRunStatus
ENGINE_RUN_STATUS_FAILED: EngineRunStatus
ENGINE_RUN_STATUS_CANCELLED: EngineRunStatus
ENGINE_RUN_EXECUTION_CATEGORY_UNSPECIFIED: EngineRunExecutionCategory
ENGINE_RUN_EXECUTION_CATEGORY_READ: EngineRunExecutionCategory
ENGINE_RUN_EXECUTION_CATEGORY_STEP: EngineRunExecutionCategory
ENGINE_RUN_EXECUTION_CATEGORY_PLAN: EngineRunExecutionCategory
ENGINE_RUN_EXECUTION_CATEGORY_COMPUTE: EngineRunExecutionCategory
ENGINE_RUN_EXECUTION_CATEGORY_WRITE: EngineRunExecutionCategory
SCHEMA_DIFF_STATUS_UNSPECIFIED: SchemaDiffStatus
SCHEMA_DIFF_STATUS_ADDED: SchemaDiffStatus
SCHEMA_DIFF_STATUS_REMOVED: SchemaDiffStatus
SCHEMA_DIFF_STATUS_TYPE_CHANGED: SchemaDiffStatus
HEALTH_CHECK_TYPE_UNSPECIFIED: HealthCheckType
HEALTH_CHECK_TYPE_ROW_COUNT: HealthCheckType
HEALTH_CHECK_TYPE_COLUMN_NULL: HealthCheckType
HEALTH_CHECK_TYPE_COLUMN_UNIQUE: HealthCheckType
HEALTH_CHECK_TYPE_COLUMN_RANGE: HealthCheckType
HEALTH_CHECK_TYPE_COLUMN_COUNT: HealthCheckType
HEALTH_CHECK_TYPE_NULL_PERCENTAGE: HealthCheckType
HEALTH_CHECK_TYPE_DUPLICATE_PERCENTAGE: HealthCheckType
RUNTIME_PAYLOAD_KIND_UNSPECIFIED: RuntimePayloadKind
RUNTIME_PAYLOAD_KIND_BUILD: RuntimePayloadKind
RUNTIME_PAYLOAD_KIND_ENGINE: RuntimePayloadKind
RUNTIME_PAYLOAD_KIND_JOB: RuntimePayloadKind
RUNTIME_PAYLOAD_KIND_COMPUTE_REQUEST: RuntimePayloadKind
RUNTIME_PAYLOAD_KIND_COMPUTE_RESPONSE: RuntimePayloadKind
RUNTIME_WORKER_KIND_UNSPECIFIED: RuntimeWorkerKind
RUNTIME_WORKER_KIND_API: RuntimeWorkerKind
RUNTIME_WORKER_KIND_BUILD_MANAGER: RuntimeWorkerKind
RUNTIME_WORKER_KIND_BUILD_WORKER: RuntimeWorkerKind
RUNTIME_WORKER_KIND_SCHEDULER: RuntimeWorkerKind
FILTER_VALUE_TYPE_UNSPECIFIED: FilterValueType
FILTER_VALUE_TYPE_STRING: FilterValueType
FILTER_VALUE_TYPE_NUMBER: FilterValueType
FILTER_VALUE_TYPE_DATE: FilterValueType
FILTER_VALUE_TYPE_DATETIME: FilterValueType
FILTER_VALUE_TYPE_COLUMN: FilterValueType
FILTER_VALUE_TYPE_BOOLEAN: FilterValueType
FILTER_LOGIC_UNSPECIFIED: FilterLogic
FILTER_LOGIC_AND: FilterLogic
FILTER_LOGIC_OR: FilterLogic
FILTER_OPERATOR_UNSPECIFIED: FilterOperator
FILTER_OPERATOR_EQUAL: FilterOperator
FILTER_OPERATOR_DOUBLE_EQUAL: FilterOperator
FILTER_OPERATOR_NOT_EQUAL: FilterOperator
FILTER_OPERATOR_GREATER_THAN: FilterOperator
FILTER_OPERATOR_LESS_THAN: FilterOperator
FILTER_OPERATOR_GREATER_EQUAL: FilterOperator
FILTER_OPERATOR_LESS_EQUAL: FilterOperator
FILTER_OPERATOR_CONTAINS: FilterOperator
FILTER_OPERATOR_NOT_CONTAINS: FilterOperator
FILTER_OPERATOR_STARTS_WITH: FilterOperator
FILTER_OPERATOR_ENDS_WITH: FilterOperator
FILTER_OPERATOR_REGEX: FilterOperator
FILTER_OPERATOR_IS_NULL: FilterOperator
FILTER_OPERATOR_IS_NOT_NULL: FilterOperator
FILTER_OPERATOR_IN: FilterOperator
FILTER_OPERATOR_NOT_IN: FilterOperator
STRING_TRANSFORM_METHOD_UNSPECIFIED: StringTransformMethod
STRING_TRANSFORM_METHOD_UPPERCASE: StringTransformMethod
STRING_TRANSFORM_METHOD_LOWERCASE: StringTransformMethod
STRING_TRANSFORM_METHOD_TITLE: StringTransformMethod
STRING_TRANSFORM_METHOD_STRIP: StringTransformMethod
STRING_TRANSFORM_METHOD_LSTRIP: StringTransformMethod
STRING_TRANSFORM_METHOD_RSTRIP: StringTransformMethod
STRING_TRANSFORM_METHOD_LENGTH: StringTransformMethod
STRING_TRANSFORM_METHOD_SLICE: StringTransformMethod
STRING_TRANSFORM_METHOD_REPLACE: StringTransformMethod
STRING_TRANSFORM_METHOD_EXTRACT: StringTransformMethod
STRING_TRANSFORM_METHOD_SPLIT: StringTransformMethod
STRING_TRANSFORM_METHOD_SPLIT_TAKE: StringTransformMethod
TIMESERIES_OPERATION_TYPE_UNSPECIFIED: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_EXTRACT: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_TIMESTAMP: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_ADD: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_SUBTRACT: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_OFFSET: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_DIFF: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_TRUNCATE: TimeseriesOperationType
TIMESERIES_OPERATION_TYPE_ROUND: TimeseriesOperationType
TIME_COMPONENT_UNSPECIFIED: TimeComponent
TIME_COMPONENT_YEAR: TimeComponent
TIME_COMPONENT_MONTH: TimeComponent
TIME_COMPONENT_DAY: TimeComponent
TIME_COMPONENT_HOUR: TimeComponent
TIME_COMPONENT_MINUTE: TimeComponent
TIME_COMPONENT_SECOND: TimeComponent
TIME_COMPONENT_QUARTER: TimeComponent
TIME_COMPONENT_WEEK: TimeComponent
TIME_COMPONENT_DAYOFWEEK: TimeComponent
DURATION_UNIT_UNSPECIFIED: DurationUnit
DURATION_UNIT_SECONDS: DurationUnit
DURATION_UNIT_MINUTES: DurationUnit
DURATION_UNIT_HOURS: DurationUnit
DURATION_UNIT_DAYS: DurationUnit
DURATION_UNIT_WEEKS: DurationUnit
DURATION_UNIT_MONTHS: DurationUnit
TIME_DIRECTION_UNSPECIFIED: TimeDirection
TIME_DIRECTION_ADD: TimeDirection
TIME_DIRECTION_SUBTRACT: TimeDirection
WITH_COLUMNS_EXPR_TYPE_UNSPECIFIED: WithColumnsExprType
WITH_COLUMNS_EXPR_TYPE_LITERAL: WithColumnsExprType
WITH_COLUMNS_EXPR_TYPE_COLUMN: WithColumnsExprType
WITH_COLUMNS_EXPR_TYPE_UDF: WithColumnsExprType
NOTIFICATION_METHOD_UNSPECIFIED: NotificationMethod
NOTIFICATION_METHOD_EMAIL: NotificationMethod
NOTIFICATION_METHOD_TELEGRAM: NotificationMethod
JOIN_HOW_UNSPECIFIED: JoinHow
JOIN_HOW_INNER: JoinHow
JOIN_HOW_LEFT: JoinHow
JOIN_HOW_RIGHT: JoinHow
JOIN_HOW_OUTER: JoinHow
JOIN_HOW_CROSS: JoinHow
GROUP_BY_AGGREGATION_FUNCTION_UNSPECIFIED: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_SUM: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_MEAN: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_COUNT: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_MIN: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_MAX: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_FIRST: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_LAST: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_MEDIAN: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_STD: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_N_UNIQUE: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_COLLECT_LIST: GroupByAggregationFunction
GROUP_BY_AGGREGATION_FUNCTION_COLLECT_SET: GroupByAggregationFunction
CHART_AGGREGATION_UNSPECIFIED: ChartAggregation
CHART_AGGREGATION_SUM: ChartAggregation
CHART_AGGREGATION_MEAN: ChartAggregation
CHART_AGGREGATION_COUNT: ChartAggregation
CHART_AGGREGATION_MIN: ChartAggregation
CHART_AGGREGATION_MAX: ChartAggregation
CHART_AGGREGATION_MEDIAN: ChartAggregation
CHART_AGGREGATION_STD: ChartAggregation
CHART_AGGREGATION_VARIANCE: ChartAggregation
CHART_AGGREGATION_UNIQUE_COUNT: ChartAggregation
OVERLAY_CHART_TYPE_UNSPECIFIED: OverlayChartType
OVERLAY_CHART_TYPE_LINE: OverlayChartType
OVERLAY_CHART_TYPE_AREA: OverlayChartType
OVERLAY_CHART_TYPE_BAR: OverlayChartType
OVERLAY_CHART_TYPE_SCATTER: OverlayChartType
Y_AXIS_POSITION_UNSPECIFIED: YAxisPosition
Y_AXIS_POSITION_LEFT: YAxisPosition
Y_AXIS_POSITION_RIGHT: YAxisPosition
REFERENCE_AXIS_UNSPECIFIED: ReferenceAxis
REFERENCE_AXIS_X: ReferenceAxis
REFERENCE_AXIS_Y: ReferenceAxis
SORT_DIRECTION_UNSPECIFIED: SortDirection
SORT_DIRECTION_ASC: SortDirection
SORT_DIRECTION_DESC: SortDirection
GROUP_SORT_BY_UNSPECIFIED: GroupSortBy
GROUP_SORT_BY_NAME: GroupSortBy
GROUP_SORT_BY_VALUE: GroupSortBy
GROUP_SORT_BY_CUSTOM: GroupSortBy
SORT_BY_UNSPECIFIED: SortBy
SORT_BY_X: SortBy
SORT_BY_Y: SortBy
SORT_BY_CUSTOM: SortBy
STACK_MODE_UNSPECIFIED: StackMode
STACK_MODE_GROUPED: StackMode
STACK_MODE_STACKED: StackMode
STACK_MODE_STACKED_100: StackMode
DATE_BUCKET_UNSPECIFIED: DateBucket
DATE_BUCKET_EXACT: DateBucket
DATE_BUCKET_YEAR: DateBucket
DATE_BUCKET_QUARTER: DateBucket
DATE_BUCKET_MONTH: DateBucket
DATE_BUCKET_WEEK: DateBucket
DATE_BUCKET_DAY: DateBucket
DATE_BUCKET_HOUR: DateBucket
DATE_ORDINAL_UNSPECIFIED: DateOrdinal
DATE_ORDINAL_DAY_OF_WEEK: DateOrdinal
DATE_ORDINAL_MONTH_OF_YEAR: DateOrdinal
DATE_ORDINAL_QUARTER_OF_YEAR: DateOrdinal
AXIS_SCALE_UNSPECIFIED: AxisScale
AXIS_SCALE_LINEAR: AxisScale
AXIS_SCALE_LOG: AxisScale
DISPLAY_UNITS_UNSPECIFIED: DisplayUnits
DISPLAY_UNITS_NONE: DisplayUnits
DISPLAY_UNITS_THOUSANDS: DisplayUnits
DISPLAY_UNITS_MILLIONS: DisplayUnits
DISPLAY_UNITS_BILLIONS: DisplayUnits
DISPLAY_UNITS_PERCENT: DisplayUnits
LEGEND_POSITION_UNSPECIFIED: LegendPosition
LEGEND_POSITION_TOP: LegendPosition
LEGEND_POSITION_BOTTOM: LegendPosition
LEGEND_POSITION_LEFT: LegendPosition
LEGEND_POSITION_RIGHT: LegendPosition
LEGEND_POSITION_NONE: LegendPosition
CHART_HEIGHT_UNSPECIFIED: ChartHeight
CHART_HEIGHT_SMALL: ChartHeight
CHART_HEIGHT_MEDIUM: ChartHeight
CHART_HEIGHT_LARGE: ChartHeight
CHART_HEIGHT_XLARGE: ChartHeight
CHART_WIDTH_UNSPECIFIED: ChartWidth
CHART_WIDTH_NORMAL: ChartWidth
CHART_WIDTH_WIDE: ChartWidth
CHART_WIDTH_FULL: ChartWidth
RECIPIENT_SOURCE_UNSPECIFIED: RecipientSource
RECIPIENT_SOURCE_MANUAL: RecipientSource
RECIPIENT_SOURCE_COLUMN: RecipientSource
AI_PROVIDER_UNSPECIFIED: AIProvider
AI_PROVIDER_OLLAMA: AIProvider
AI_PROVIDER_OPENAI: AIProvider
AI_PROVIDER_OPENROUTER: AIProvider
AI_PROVIDER_HUGGINGFACE: AIProvider
DEDUPLICATE_KEEP_UNSPECIFIED: DeduplicateKeep
DEDUPLICATE_KEEP_FIRST: DeduplicateKeep
DEDUPLICATE_KEEP_LAST: DeduplicateKeep
DEDUPLICATE_KEEP_ANY: DeduplicateKeep
DEDUPLICATE_KEEP_NONE: DeduplicateKeep
PIVOT_AGGREGATE_FUNCTION_UNSPECIFIED: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_FIRST: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_LAST: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_SUM: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_MEAN: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_MEDIAN: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_MIN: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_MAX: PivotAggregateFunction
PIVOT_AGGREGATE_FUNCTION_COUNT: PivotAggregateFunction
FILL_NULL_STRATEGY_UNSPECIFIED: FillNullStrategy
FILL_NULL_STRATEGY_FORWARD: FillNullStrategy
FILL_NULL_STRATEGY_BACKWARD: FillNullStrategy
FILL_NULL_STRATEGY_MEAN: FillNullStrategy
FILL_NULL_STRATEGY_MEDIAN: FillNullStrategy
FILL_NULL_STRATEGY_ZERO: FillNullStrategy
FILL_NULL_STRATEGY_LITERAL: FillNullStrategy
FILL_NULL_STRATEGY_DROP_ROWS: FillNullStrategy
