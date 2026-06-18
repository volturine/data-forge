import {
	AIProvider as ProtocolAIProvider,
	ActiveBuildStatus as ProtocolActiveBuildStatus,
	AxisScale as ProtocolAxisScale,
	BuildLogLevel as ProtocolBuildLogLevel,
	BuildStepState as ProtocolBuildStepState,
	BuildTabStatus as ProtocolBuildTabStatus,
	ChartAggregation as ProtocolChartAggregation,
	ChartHeight as ProtocolChartHeight,
	ChartType as ProtocolChartType,
	ChartWidth as ProtocolChartWidth,
	DateBucket as ProtocolDateBucket,
	DateOrdinal as ProtocolDateOrdinal,
	DeduplicateKeep as ProtocolDeduplicateKeep,
	DisplayUnits as ProtocolDisplayUnits,
	DurationUnit as ProtocolDurationUnit,
	EngineRunKind as ProtocolEngineRunKind,
	FillNullStrategy as ProtocolFillNullStrategy,
	FilterLogic as ProtocolFilterLogic,
	FilterOperator as ProtocolFilterOperator,
	FilterValueType as ProtocolFilterValueType,
	GroupByAggregationFunction as ProtocolGroupByAggregationFunction,
	GroupSortBy as ProtocolGroupSortBy,
	JoinHow as ProtocolJoinHow,
	LegendPosition as ProtocolLegendPosition,
	NotificationMethod as ProtocolNotificationMethod,
	OverlayChartType as ProtocolOverlayChartType,
	PivotAggregateFunction as ProtocolPivotAggregateFunction,
	RecipientSource as ProtocolRecipientSource,
	ReferenceAxis as ProtocolReferenceAxis,
	SortBy as ProtocolSortBy,
	SortDirection as ProtocolSortDirection,
	StackMode as ProtocolStackMode,
	StringTransformMethod as ProtocolStringTransformMethod,
	TimeComponent as ProtocolTimeComponent,
	TimeDirection as ProtocolTimeDirection,
	TimeseriesOperationType as ProtocolTimeseriesOperationType,
	WithColumnsExprType as ProtocolWithColumnsExprType,
	YAxisPosition as ProtocolYAxisPosition
} from '$lib/protocol/dataforge_protocol/enums_pb';

type EnumToken<T extends object> = T[keyof T];

export const FILTER_OPERATOR_TOKENS = {
	[ProtocolFilterOperator.EQUAL]: '=',
	[ProtocolFilterOperator.DOUBLE_EQUAL]: '==',
	[ProtocolFilterOperator.NOT_EQUAL]: '!=',
	[ProtocolFilterOperator.GREATER_THAN]: '>',
	[ProtocolFilterOperator.LESS_THAN]: '<',
	[ProtocolFilterOperator.GREATER_EQUAL]: '>=',
	[ProtocolFilterOperator.LESS_EQUAL]: '<=',
	[ProtocolFilterOperator.CONTAINS]: 'contains',
	[ProtocolFilterOperator.NOT_CONTAINS]: 'not_contains',
	[ProtocolFilterOperator.STARTS_WITH]: 'starts_with',
	[ProtocolFilterOperator.ENDS_WITH]: 'ends_with',
	[ProtocolFilterOperator.REGEX]: 'regex',
	[ProtocolFilterOperator.IS_NULL]: 'is_null',
	[ProtocolFilterOperator.IS_NOT_NULL]: 'is_not_null',
	[ProtocolFilterOperator.IN]: 'in',
	[ProtocolFilterOperator.NOT_IN]: 'not_in'
} as const satisfies Partial<Record<ProtocolFilterOperator, string>>;

export const FILTER_VALUE_TYPE_TOKENS = {
	[ProtocolFilterValueType.STRING]: 'string',
	[ProtocolFilterValueType.NUMBER]: 'number',
	[ProtocolFilterValueType.DATE]: 'date',
	[ProtocolFilterValueType.DATETIME]: 'datetime',
	[ProtocolFilterValueType.COLUMN]: 'column',
	[ProtocolFilterValueType.BOOLEAN]: 'boolean'
} as const satisfies Partial<Record<ProtocolFilterValueType, string>>;

export const FILTER_LOGIC_TOKENS = {
	[ProtocolFilterLogic.AND]: 'AND',
	[ProtocolFilterLogic.OR]: 'OR'
} as const satisfies Partial<Record<ProtocolFilterLogic, string>>;

export const GROUP_BY_AGGREGATION_FUNCTION_TOKENS = {
	[ProtocolGroupByAggregationFunction.SUM]: 'sum',
	[ProtocolGroupByAggregationFunction.MEAN]: 'mean',
	[ProtocolGroupByAggregationFunction.COUNT]: 'count',
	[ProtocolGroupByAggregationFunction.MIN]: 'min',
	[ProtocolGroupByAggregationFunction.MAX]: 'max',
	[ProtocolGroupByAggregationFunction.FIRST]: 'first',
	[ProtocolGroupByAggregationFunction.LAST]: 'last',
	[ProtocolGroupByAggregationFunction.MEDIAN]: 'median',
	[ProtocolGroupByAggregationFunction.STD]: 'std',
	[ProtocolGroupByAggregationFunction.N_UNIQUE]: 'n_unique',
	[ProtocolGroupByAggregationFunction.COLLECT_LIST]: 'collect_list',
	[ProtocolGroupByAggregationFunction.COLLECT_SET]: 'collect_set'
} as const satisfies Partial<Record<ProtocolGroupByAggregationFunction, string>>;

export const WITH_COLUMNS_EXPR_TYPE_TOKENS = {
	[ProtocolWithColumnsExprType.LITERAL]: 'literal',
	[ProtocolWithColumnsExprType.COLUMN]: 'column',
	[ProtocolWithColumnsExprType.UDF]: 'udf'
} as const satisfies Partial<Record<ProtocolWithColumnsExprType, string>>;

export const DEDUPLICATE_KEEP_TOKENS = {
	[ProtocolDeduplicateKeep.FIRST]: 'first',
	[ProtocolDeduplicateKeep.LAST]: 'last',
	[ProtocolDeduplicateKeep.ANY]: 'any',
	[ProtocolDeduplicateKeep.NONE]: 'none'
} as const satisfies Partial<Record<ProtocolDeduplicateKeep, string>>;

export const FILL_NULL_STRATEGY_TOKENS = {
	[ProtocolFillNullStrategy.FORWARD]: 'forward',
	[ProtocolFillNullStrategy.BACKWARD]: 'backward',
	[ProtocolFillNullStrategy.MEAN]: 'mean',
	[ProtocolFillNullStrategy.MEDIAN]: 'median',
	[ProtocolFillNullStrategy.ZERO]: 'zero',
	[ProtocolFillNullStrategy.LITERAL]: 'literal',
	[ProtocolFillNullStrategy.DROP_ROWS]: 'drop_rows'
} as const satisfies Partial<Record<ProtocolFillNullStrategy, string>>;

export const PIVOT_AGGREGATE_FUNCTION_TOKENS = {
	[ProtocolPivotAggregateFunction.FIRST]: 'first',
	[ProtocolPivotAggregateFunction.LAST]: 'last',
	[ProtocolPivotAggregateFunction.SUM]: 'sum',
	[ProtocolPivotAggregateFunction.MEAN]: 'mean',
	[ProtocolPivotAggregateFunction.MEDIAN]: 'median',
	[ProtocolPivotAggregateFunction.MIN]: 'min',
	[ProtocolPivotAggregateFunction.MAX]: 'max',
	[ProtocolPivotAggregateFunction.COUNT]: 'count'
} as const satisfies Partial<Record<ProtocolPivotAggregateFunction, string>>;

export const JOIN_HOW_TOKENS = {
	[ProtocolJoinHow.INNER]: 'inner',
	[ProtocolJoinHow.LEFT]: 'left',
	[ProtocolJoinHow.RIGHT]: 'right',
	[ProtocolJoinHow.OUTER]: 'outer',
	[ProtocolJoinHow.CROSS]: 'cross'
} as const satisfies Partial<Record<ProtocolJoinHow, string>>;

export const OVERLAY_CHART_TYPE_TOKENS = {
	[ProtocolOverlayChartType.LINE]: 'line',
	[ProtocolOverlayChartType.AREA]: 'area',
	[ProtocolOverlayChartType.BAR]: 'bar',
	[ProtocolOverlayChartType.SCATTER]: 'scatter'
} as const satisfies Partial<Record<ProtocolOverlayChartType, string>>;

export const CHART_AGGREGATION_TOKENS = {
	[ProtocolChartAggregation.SUM]: 'sum',
	[ProtocolChartAggregation.MEAN]: 'mean',
	[ProtocolChartAggregation.COUNT]: 'count',
	[ProtocolChartAggregation.MIN]: 'min',
	[ProtocolChartAggregation.MAX]: 'max',
	[ProtocolChartAggregation.MEDIAN]: 'median',
	[ProtocolChartAggregation.STD]: 'std',
	[ProtocolChartAggregation.VARIANCE]: 'variance',
	[ProtocolChartAggregation.UNIQUE_COUNT]: 'unique_count'
} as const satisfies Partial<Record<ProtocolChartAggregation, string>>;

export const Y_AXIS_POSITION_TOKENS = {
	[ProtocolYAxisPosition.LEFT]: 'left',
	[ProtocolYAxisPosition.RIGHT]: 'right'
} as const satisfies Partial<Record<ProtocolYAxisPosition, string>>;

export const REFERENCE_AXIS_TOKENS = {
	[ProtocolReferenceAxis.X]: 'x',
	[ProtocolReferenceAxis.Y]: 'y'
} as const satisfies Partial<Record<ProtocolReferenceAxis, string>>;

export const CHART_TYPE_TOKENS = {
	[ProtocolChartType.BAR]: 'bar',
	[ProtocolChartType.HORIZONTAL_BAR]: 'horizontal_bar',
	[ProtocolChartType.AREA]: 'area',
	[ProtocolChartType.HEATGRID]: 'heatgrid',
	[ProtocolChartType.HISTOGRAM]: 'histogram',
	[ProtocolChartType.SCATTER]: 'scatter',
	[ProtocolChartType.LINE]: 'line',
	[ProtocolChartType.PIE]: 'pie',
	[ProtocolChartType.BOXPLOT]: 'boxplot'
} as const satisfies Partial<Record<ProtocolChartType, string>>;

export const GROUP_SORT_BY_TOKENS = {
	[ProtocolGroupSortBy.NAME]: 'name',
	[ProtocolGroupSortBy.VALUE]: 'value',
	[ProtocolGroupSortBy.CUSTOM]: 'custom'
} as const satisfies Partial<Record<ProtocolGroupSortBy, string>>;

export const SORT_DIRECTION_TOKENS = {
	[ProtocolSortDirection.ASC]: 'asc',
	[ProtocolSortDirection.DESC]: 'desc'
} as const satisfies Partial<Record<ProtocolSortDirection, string>>;

export const STACK_MODE_TOKENS = {
	[ProtocolStackMode.GROUPED]: 'grouped',
	[ProtocolStackMode.STACKED]: 'stacked',
	[ProtocolStackMode.STACKED_100]: '100%'
} as const satisfies Partial<Record<ProtocolStackMode, string>>;

export const DATE_BUCKET_TOKENS = {
	[ProtocolDateBucket.EXACT]: 'exact',
	[ProtocolDateBucket.YEAR]: 'year',
	[ProtocolDateBucket.QUARTER]: 'quarter',
	[ProtocolDateBucket.MONTH]: 'month',
	[ProtocolDateBucket.WEEK]: 'week',
	[ProtocolDateBucket.DAY]: 'day',
	[ProtocolDateBucket.HOUR]: 'hour'
} as const satisfies Partial<Record<ProtocolDateBucket, string>>;

export const DATE_ORDINAL_TOKENS = {
	[ProtocolDateOrdinal.DAY_OF_WEEK]: 'day_of_week',
	[ProtocolDateOrdinal.MONTH_OF_YEAR]: 'month_of_year',
	[ProtocolDateOrdinal.QUARTER_OF_YEAR]: 'quarter_of_year'
} as const satisfies Partial<Record<ProtocolDateOrdinal, string>>;

export const SORT_BY_TOKENS = {
	[ProtocolSortBy.X]: 'x',
	[ProtocolSortBy.Y]: 'y',
	[ProtocolSortBy.CUSTOM]: 'custom'
} as const satisfies Partial<Record<ProtocolSortBy, string>>;

export const AXIS_SCALE_TOKENS = {
	[ProtocolAxisScale.LINEAR]: 'linear',
	[ProtocolAxisScale.LOG]: 'log'
} as const satisfies Partial<Record<ProtocolAxisScale, string>>;

export const DISPLAY_UNITS_TOKENS = {
	[ProtocolDisplayUnits.NONE]: '',
	[ProtocolDisplayUnits.THOUSANDS]: 'K',
	[ProtocolDisplayUnits.MILLIONS]: 'M',
	[ProtocolDisplayUnits.BILLIONS]: 'B',
	[ProtocolDisplayUnits.PERCENT]: '%'
} as const satisfies Partial<Record<ProtocolDisplayUnits, string>>;

export const LEGEND_POSITION_TOKENS = {
	[ProtocolLegendPosition.TOP]: 'top',
	[ProtocolLegendPosition.BOTTOM]: 'bottom',
	[ProtocolLegendPosition.LEFT]: 'left',
	[ProtocolLegendPosition.RIGHT]: 'right',
	[ProtocolLegendPosition.NONE]: 'none'
} as const satisfies Partial<Record<ProtocolLegendPosition, string>>;

export const CHART_HEIGHT_TOKENS = {
	[ProtocolChartHeight.SMALL]: 'small',
	[ProtocolChartHeight.MEDIUM]: 'medium',
	[ProtocolChartHeight.LARGE]: 'large',
	[ProtocolChartHeight.XLARGE]: 'xlarge'
} as const satisfies Partial<Record<ProtocolChartHeight, string>>;

export const CHART_WIDTH_TOKENS = {
	[ProtocolChartWidth.NORMAL]: 'normal',
	[ProtocolChartWidth.WIDE]: 'wide',
	[ProtocolChartWidth.FULL]: 'full'
} as const satisfies Partial<Record<ProtocolChartWidth, string>>;

export const NOTIFICATION_METHOD_TOKENS = {
	[ProtocolNotificationMethod.EMAIL]: 'email',
	[ProtocolNotificationMethod.TELEGRAM]: 'telegram'
} as const satisfies Partial<Record<ProtocolNotificationMethod, string>>;

export const RECIPIENT_SOURCE_TOKENS = {
	[ProtocolRecipientSource.MANUAL]: 'manual',
	[ProtocolRecipientSource.COLUMN]: 'column'
} as const satisfies Partial<Record<ProtocolRecipientSource, string>>;

export const AI_PROVIDER_TOKENS = {
	[ProtocolAIProvider.AI_PROVIDER_OLLAMA]: 'ollama',
	[ProtocolAIProvider.AI_PROVIDER_OPENAI]: 'openai',
	[ProtocolAIProvider.AI_PROVIDER_OPENROUTER]: 'openrouter',
	[ProtocolAIProvider.AI_PROVIDER_HUGGINGFACE]: 'huggingface'
} as const satisfies Partial<Record<ProtocolAIProvider, string>>;

export const TIMESERIES_OPERATION_TYPE_TOKENS = {
	[ProtocolTimeseriesOperationType.EXTRACT]: 'extract',
	[ProtocolTimeseriesOperationType.TIMESTAMP]: 'timestamp',
	[ProtocolTimeseriesOperationType.ADD]: 'add',
	[ProtocolTimeseriesOperationType.SUBTRACT]: 'subtract',
	[ProtocolTimeseriesOperationType.OFFSET]: 'offset',
	[ProtocolTimeseriesOperationType.DIFF]: 'diff',
	[ProtocolTimeseriesOperationType.TRUNCATE]: 'truncate',
	[ProtocolTimeseriesOperationType.ROUND]: 'round'
} as const satisfies Partial<Record<ProtocolTimeseriesOperationType, string>>;

export const TIME_COMPONENT_TOKENS = {
	[ProtocolTimeComponent.YEAR]: 'year',
	[ProtocolTimeComponent.MONTH]: 'month',
	[ProtocolTimeComponent.DAY]: 'day',
	[ProtocolTimeComponent.HOUR]: 'hour',
	[ProtocolTimeComponent.MINUTE]: 'minute',
	[ProtocolTimeComponent.SECOND]: 'second',
	[ProtocolTimeComponent.QUARTER]: 'quarter',
	[ProtocolTimeComponent.WEEK]: 'week',
	[ProtocolTimeComponent.DAYOFWEEK]: 'dayofweek'
} as const satisfies Partial<Record<ProtocolTimeComponent, string>>;

export const DURATION_UNIT_TOKENS = {
	[ProtocolDurationUnit.SECONDS]: 'seconds',
	[ProtocolDurationUnit.MINUTES]: 'minutes',
	[ProtocolDurationUnit.HOURS]: 'hours',
	[ProtocolDurationUnit.DAYS]: 'days',
	[ProtocolDurationUnit.WEEKS]: 'weeks',
	[ProtocolDurationUnit.MONTHS]: 'months'
} as const satisfies Partial<Record<ProtocolDurationUnit, string>>;

export const TIME_DIRECTION_TOKENS = {
	[ProtocolTimeDirection.ADD]: 'add',
	[ProtocolTimeDirection.SUBTRACT]: 'subtract'
} as const satisfies Partial<Record<ProtocolTimeDirection, string>>;

export const STRING_TRANSFORM_METHOD_TOKENS = {
	[ProtocolStringTransformMethod.UPPERCASE]: 'uppercase',
	[ProtocolStringTransformMethod.LOWERCASE]: 'lowercase',
	[ProtocolStringTransformMethod.TITLE]: 'title',
	[ProtocolStringTransformMethod.STRIP]: 'strip',
	[ProtocolStringTransformMethod.LSTRIP]: 'lstrip',
	[ProtocolStringTransformMethod.RSTRIP]: 'rstrip',
	[ProtocolStringTransformMethod.LENGTH]: 'length',
	[ProtocolStringTransformMethod.SLICE]: 'slice',
	[ProtocolStringTransformMethod.REPLACE]: 'replace',
	[ProtocolStringTransformMethod.EXTRACT]: 'extract',
	[ProtocolStringTransformMethod.SPLIT]: 'split',
	[ProtocolStringTransformMethod.SPLIT_TAKE]: 'split_take'
} as const satisfies Partial<Record<ProtocolStringTransformMethod, string>>;

export const ENGINE_RUN_KIND_TOKENS = {
	[ProtocolEngineRunKind.BUILD]: 'build',
	[ProtocolEngineRunKind.PREVIEW]: 'preview',
	[ProtocolEngineRunKind.ROW_COUNT]: 'row_count',
	[ProtocolEngineRunKind.DOWNLOAD]: 'download',
	[ProtocolEngineRunKind.INGEST]: 'ingest'
} as const satisfies Partial<Record<ProtocolEngineRunKind, string>>;

export const BUILD_STEP_STATE_TOKENS = {
	[ProtocolBuildStepState.PENDING]: 'pending',
	[ProtocolBuildStepState.RUNNING]: 'running',
	[ProtocolBuildStepState.COMPLETED]: 'completed',
	[ProtocolBuildStepState.FAILED]: 'failed',
	[ProtocolBuildStepState.SKIPPED]: 'skipped'
} as const satisfies Partial<Record<ProtocolBuildStepState, string>>;

export const ACTIVE_BUILD_STATUS_TOKENS = {
	[ProtocolActiveBuildStatus.QUEUED]: 'queued',
	[ProtocolActiveBuildStatus.RUNNING]: 'running',
	[ProtocolActiveBuildStatus.COMPLETED]: 'completed',
	[ProtocolActiveBuildStatus.FAILED]: 'failed',
	[ProtocolActiveBuildStatus.CANCELLED]: 'cancelled'
} as const satisfies Partial<Record<ProtocolActiveBuildStatus, string>>;

export const BUILD_TAB_STATUS_TOKENS = {
	[ProtocolBuildTabStatus.SUCCESS]: 'success',
	[ProtocolBuildTabStatus.FAILED]: 'failed'
} as const satisfies Partial<Record<ProtocolBuildTabStatus, string>>;

export const BUILD_LOG_LEVEL_TOKENS = {
	[ProtocolBuildLogLevel.INFO]: 'info',
	[ProtocolBuildLogLevel.WARNING]: 'warning',
	[ProtocolBuildLogLevel.ERROR]: 'error'
} as const satisfies Partial<Record<ProtocolBuildLogLevel, string>>;

export type FilterOperator = EnumToken<typeof FILTER_OPERATOR_TOKENS>;
export type FilterValueType = EnumToken<typeof FILTER_VALUE_TYPE_TOKENS>;
export type FilterLogic = EnumToken<typeof FILTER_LOGIC_TOKENS>;
export type GroupByAggregationFunction = EnumToken<typeof GROUP_BY_AGGREGATION_FUNCTION_TOKENS>;
export type WithColumnsExprType = EnumToken<typeof WITH_COLUMNS_EXPR_TYPE_TOKENS>;
export type DeduplicateKeep = EnumToken<typeof DEDUPLICATE_KEEP_TOKENS>;
export type FillNullStrategy = EnumToken<typeof FILL_NULL_STRATEGY_TOKENS>;
export type PivotAggregateFunction = EnumToken<typeof PIVOT_AGGREGATE_FUNCTION_TOKENS>;
export type JoinHow = EnumToken<typeof JOIN_HOW_TOKENS>;
export type OverlayChartType = EnumToken<typeof OVERLAY_CHART_TYPE_TOKENS>;
export type ChartAggregation = EnumToken<typeof CHART_AGGREGATION_TOKENS>;
export type YAxisPosition = EnumToken<typeof Y_AXIS_POSITION_TOKENS>;
export type ReferenceAxis = EnumToken<typeof REFERENCE_AXIS_TOKENS>;
export type ChartType = EnumToken<typeof CHART_TYPE_TOKENS>;
export type GroupSortBy = EnumToken<typeof GROUP_SORT_BY_TOKENS>;
export type SortDirection = EnumToken<typeof SORT_DIRECTION_TOKENS>;
export type StackMode = EnumToken<typeof STACK_MODE_TOKENS>;
export type DateBucket = EnumToken<typeof DATE_BUCKET_TOKENS>;
export type DateOrdinal = EnumToken<typeof DATE_ORDINAL_TOKENS>;
export type SortBy = EnumToken<typeof SORT_BY_TOKENS>;
export type AxisScale = EnumToken<typeof AXIS_SCALE_TOKENS>;
export type DisplayUnits = EnumToken<typeof DISPLAY_UNITS_TOKENS>;
export type LegendPosition = EnumToken<typeof LEGEND_POSITION_TOKENS>;
export type ChartHeight = EnumToken<typeof CHART_HEIGHT_TOKENS>;
export type ChartWidth = EnumToken<typeof CHART_WIDTH_TOKENS>;
export type NotificationMethod = EnumToken<typeof NOTIFICATION_METHOD_TOKENS>;
export type RecipientSource = EnumToken<typeof RECIPIENT_SOURCE_TOKENS>;
export type AIProvider = EnumToken<typeof AI_PROVIDER_TOKENS>;
export type TimeseriesOperationType = EnumToken<typeof TIMESERIES_OPERATION_TYPE_TOKENS>;
export type TimeComponent = EnumToken<typeof TIME_COMPONENT_TOKENS>;
export type DurationUnit = EnumToken<typeof DURATION_UNIT_TOKENS>;
export type TimeDirection = EnumToken<typeof TIME_DIRECTION_TOKENS>;
export type StringTransformMethod = EnumToken<typeof STRING_TRANSFORM_METHOD_TOKENS>;
export type EngineRunKind = EnumToken<typeof ENGINE_RUN_KIND_TOKENS>;
export type BuildStepState = EnumToken<typeof BUILD_STEP_STATE_TOKENS>;
export type ActiveBuildStatus = EnumToken<typeof ACTIVE_BUILD_STATUS_TOKENS>;
export type BuildTabStatus = EnumToken<typeof BUILD_TAB_STATUS_TOKENS>;
export type BuildLogLevel = EnumToken<typeof BUILD_LOG_LEVEL_TOKENS>;
