// UI-facing operation config types. Field value types are anchored to generated
// proto JSON types so schema changes fail TypeScript instead of drifting here.

import type {
	AIConfigJson as ProtocolAIConfigJson,
	AggregationJson as ProtocolAggregationJson,
	ChartConfigJson as ProtocolChartConfigJson,
	DeduplicateConfigJson as ProtocolDeduplicateConfigJson,
	DownloadConfigJson as ProtocolDownloadConfigJson,
	DropConfigJson as ProtocolDropConfigJson,
	ExplodeConfigJson as ProtocolExplodeConfigJson,
	ExportConfigJson as ProtocolExportConfigJson,
	ExpressionConfigJson as ProtocolExpressionConfigJson,
	FillNullConfigJson as ProtocolFillNullConfigJson,
	FilterConditionJson as ProtocolFilterConditionJson,
	FilterConfigJson as ProtocolFilterConfigJson,
	FilterValueJson as ProtocolFilterValueJson,
	GroupByConfigJson as ProtocolGroupByConfigJson,
	JoinColumnJson as ProtocolJoinColumnJson,
	JoinConfigJson as ProtocolJoinConfigJson,
	LimitConfigJson as ProtocolLimitConfigJson,
	NotificationConfigJson as ProtocolNotificationConfigJson,
	OverlayJson as ProtocolOverlayJson,
	PivotConfigJson as ProtocolPivotConfigJson,
	ReferenceLineJson as ProtocolReferenceLineJson,
	RenameConfigJson as ProtocolRenameConfigJson,
	SampleConfigJson as ProtocolSampleConfigJson,
	SelectConfigJson as ProtocolSelectConfigJson,
	SortConfigJson as ProtocolSortConfigJson,
	StringListJson as ProtocolStringListJson,
	StringTransformConfigJson as ProtocolStringTransformConfigJson,
	TimeSeriesConfigJson as ProtocolTimeSeriesConfigJson,
	TopKConfigJson as ProtocolTopKConfigJson,
	UnionByNameConfigJson as ProtocolUnionByNameConfigJson,
	UnpivotConfigJson as ProtocolUnpivotConfigJson,
	ViewConfigJson as ProtocolViewConfigJson,
	WithColumnsConfigJson as ProtocolWithColumnsConfigJson,
	WithColumnsExprJson as ProtocolWithColumnsExprJson
} from '$lib/protocol/dataforge_protocol/analysis_pb';
import type {
	AIProvider,
	AxisScale,
	CastMapType,
	ChartAggregation,
	ChartHeight,
	ChartType,
	ChartWidth,
	DateBucket,
	DateOrdinal,
	DeduplicateKeep,
	DisplayUnits,
	DurationUnit,
	ExportDestination,
	ExportFormat,
	FillNullStrategy,
	FilterLogic,
	FilterOperator,
	FilterValueType as StepFilterValueType,
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
	YAxisPosition
} from '$lib/types/protocol-enum-tokens';

type Field<T, K extends keyof T> = NonNullable<T[K]>;
type OptionalField<T, K extends keyof T> = Field<T, K> | null;
type ProtoNumber<T> = Extract<NonNullable<T>, number>;
type OptionalNumberField<T, K extends keyof T> = ProtoNumber<T[K]> | null;

export type FilterValueType = StepFilterValueType;
export type FilterConditionValue =
	| Field<ProtocolFilterValueJson, 'stringValue'>
	| ProtoNumber<ProtocolFilterValueJson['numberValue']>
	| Field<ProtocolFilterValueJson, 'boolValue'>
	| Field<ProtocolStringListJson, 'values'>
	| null;

export interface FilterCondition {
	column: Field<ProtocolFilterConditionJson, 'column'>;
	operator: FilterOperator;
	value: FilterConditionValue;
	value_type: FilterValueType;
	compare_column?: Field<ProtocolFilterConditionJson, 'compareColumn'>;
}

export interface FilterConfigData {
	conditions: Field<ProtocolFilterConfigJson, 'conditions'> extends unknown[]
		? FilterCondition[]
		: never;
	logic: FilterLogic;
}

export interface SelectConfigData {
	columns: Field<ProtocolSelectConfigJson, 'columns'>;
	cast_map?: Record<keyof Field<ProtocolSelectConfigJson, 'castMap'>, CastMapType>;
}

export interface Aggregation {
	column: Field<ProtocolAggregationJson, 'column'>;
	function: GroupByAggregationFunction;
	alias: Field<ProtocolAggregationJson, 'alias'>;
}

export interface GroupByConfigData {
	group_by: Field<ProtocolGroupByConfigJson, 'groupBy'>;
	aggregations: Field<ProtocolGroupByConfigJson, 'aggregations'> extends unknown[]
		? Aggregation[]
		: never;
}

export interface SortConfigData {
	columns: Field<ProtocolSortConfigJson, 'columns'>;
	descending: Field<ProtocolSortConfigJson, 'descending'> | boolean;
}

export interface RenameConfigData {
	column_mapping: Field<ProtocolRenameConfigJson, 'columnMapping'>;
}

export interface DropConfigData {
	columns: Field<ProtocolDropConfigJson, 'columns'>;
}

export interface JoinColumn {
	id: Field<ProtocolJoinColumnJson, 'id'>;
	left_column: Field<ProtocolJoinColumnJson, 'leftColumn'>;
	right_column: Field<ProtocolJoinColumnJson, 'rightColumn'>;
}

export interface JoinConfigData {
	how: JoinHow;
	right_source?: Field<ProtocolJoinConfigJson, 'rightSource'>;
	join_columns: Field<ProtocolJoinConfigJson, 'joinColumns'> extends unknown[]
		? JoinColumn[]
		: never;
	right_columns: Field<ProtocolJoinConfigJson, 'rightColumns'>;
	suffix: Field<ProtocolJoinConfigJson, 'suffix'>;
}

export interface ExpressionConfigData {
	expression: Field<ProtocolExpressionConfigJson, 'expression'>;
	column_name: Field<ProtocolExpressionConfigJson, 'columnName'>;
}

export interface WithColumnsExpr {
	name: Field<ProtocolWithColumnsExprJson, 'name'>;
	type: WithColumnsExprType;
	value?: FilterConditionValue;
	column?: OptionalField<ProtocolWithColumnsExprJson, 'column'>;
	args?: Field<ProtocolWithColumnsExprJson, 'args'> | null;
	code?: OptionalField<ProtocolWithColumnsExprJson, 'code'>;
	udf_id?: OptionalField<ProtocolWithColumnsExprJson, 'udfId'>;
}

export interface WithColumnsConfigData {
	expressions: Field<ProtocolWithColumnsConfigJson, 'expressions'> extends unknown[]
		? WithColumnsExpr[]
		: never;
}

export interface DeduplicateConfigData {
	subset: Field<ProtocolDeduplicateConfigJson, 'subset'>;
	keep: DeduplicateKeep;
}

export interface FillNullConfigData {
	strategy: FillNullStrategy;
	columns: Field<ProtocolFillNullConfigJson, 'columns'>;
	value?: Exclude<FilterConditionValue, boolean | string[] | null>;
	value_type?: Field<ProtocolFillNullConfigJson, 'valueType'> | CastMapType;
}

export interface ExplodeConfigData {
	columns: Field<ProtocolExplodeConfigJson, 'columns'>;
}

export interface PivotConfigData {
	index: Field<ProtocolPivotConfigJson, 'index'>;
	columns: Field<ProtocolPivotConfigJson, 'columns'>;
	values?: OptionalField<ProtocolPivotConfigJson, 'values'>;
	aggregate_function: PivotAggregateFunction;
}

export interface TimeSeriesConfigData {
	column: Field<ProtocolTimeSeriesConfigJson, 'column'>;
	operation_type: TimeseriesOperationType;
	new_column: Field<ProtocolTimeSeriesConfigJson, 'newColumn'>;
	component?: TimeComponent;
	value?: Field<ProtocolTimeSeriesConfigJson, 'value'>;
	unit?: DurationUnit;
	direction?: TimeDirection;
	column2?: Field<ProtocolTimeSeriesConfigJson, 'column2'>;
}

export interface StringMethodsConfigData {
	column: Field<ProtocolStringTransformConfigJson, 'column'>;
	method: StringTransformMethod;
	new_column: Field<ProtocolStringTransformConfigJson, 'newColumn'>;
	start?: Field<ProtocolStringTransformConfigJson, 'start'>;
	end?: OptionalField<ProtocolStringTransformConfigJson, 'end'>;
	pattern?: Field<ProtocolStringTransformConfigJson, 'pattern'>;
	replacement?: Field<ProtocolStringTransformConfigJson, 'replacement'>;
	group_index?: Field<ProtocolStringTransformConfigJson, 'groupIndex'>;
	delimiter?: Field<ProtocolStringTransformConfigJson, 'delimiter'>;
	index?: Field<ProtocolStringTransformConfigJson, 'index'>;
}

export interface ViewConfigData {
	rowLimit: Field<ProtocolViewConfigJson, 'rowLimit'>;
}

export interface SampleConfigData {
	fraction?: ProtoNumber<ProtocolSampleConfigJson['fraction']>;
	seed?: OptionalField<ProtocolSampleConfigJson, 'seed'>;
}

export interface LimitConfigData {
	n: Field<ProtocolLimitConfigJson, 'n'>;
}

export interface TopKConfigData {
	column: Field<ProtocolTopKConfigJson, 'column'>;
	k: Field<ProtocolTopKConfigJson, 'k'>;
	descending: Field<ProtocolTopKConfigJson, 'descending'>;
}

export interface UnpivotConfigData {
	index?: Field<ProtocolUnpivotConfigJson, 'idVars'>;
	on?: Field<ProtocolUnpivotConfigJson, 'valueVars'>;
	id_vars?: Field<ProtocolUnpivotConfigJson, 'idVars'>;
	value_vars?: Field<ProtocolUnpivotConfigJson, 'valueVars'>;
	variable_name?: Field<ProtocolUnpivotConfigJson, 'variableName'>;
	value_name?: Field<ProtocolUnpivotConfigJson, 'valueName'>;
}

export interface UnionByNameConfigData {
	sources: Field<ProtocolUnionByNameConfigJson, 'sources'>;
	allow_missing: Field<ProtocolUnionByNameConfigJson, 'allowMissing'>;
}

export interface ExportConfigData {
	format: ExportFormat;
	filename: Field<ProtocolExportConfigJson, 'filename'>;
	destination: ExportDestination;
}

export interface DownloadConfigData {
	format: ExportFormat;
	filename: Field<ProtocolDownloadConfigJson, 'filename'>;
}

export interface PlotConfigData {
	chart_type: ChartType;
	x_column: Field<ProtocolChartConfigJson, 'xColumn'>;
	y_column: Field<ProtocolChartConfigJson, 'yColumn'>;
	bins: Field<ProtocolChartConfigJson, 'bins'>;
	aggregation: ChartAggregation;
	group_column: OptionalField<ProtocolChartConfigJson, 'groupColumn'>;
	group_sort_by: GroupSortBy | null;
	group_sort_order: SortDirection;
	group_sort_column: OptionalField<ProtocolChartConfigJson, 'groupSortColumn'>;
	stack_mode: StackMode;
	area_opacity: ProtoNumber<ProtocolChartConfigJson['areaOpacity']>;
	date_bucket: DateBucket | null;
	date_ordinal: DateOrdinal | null;
	pan_zoom_enabled: Field<ProtocolChartConfigJson, 'panZoomEnabled'>;
	selection_enabled: Field<ProtocolChartConfigJson, 'selectionEnabled'>;
	area_selection_enabled: Field<ProtocolChartConfigJson, 'areaSelectionEnabled'>;
	sort_by: SortBy | null;
	sort_order: SortDirection;
	sort_column: OptionalField<ProtocolChartConfigJson, 'sortColumn'>;
	x_axis_label: OptionalField<ProtocolChartConfigJson, 'xAxisLabel'>;
	y_axis_label: OptionalField<ProtocolChartConfigJson, 'yAxisLabel'>;
	y_axis_scale: AxisScale;
	y_axis_min: OptionalNumberField<ProtocolChartConfigJson, 'yAxisMin'>;
	y_axis_max: OptionalNumberField<ProtocolChartConfigJson, 'yAxisMax'>;
	display_units: DisplayUnits;
	decimal_places: Field<ProtocolChartConfigJson, 'decimalPlaces'>;
	legend_position: LegendPosition;
	title: OptionalField<ProtocolChartConfigJson, 'title'>;
	series_colors: Field<ProtocolChartConfigJson, 'seriesColors'>;
	overlays: Field<ProtocolChartConfigJson, 'overlays'> extends unknown[] ? OverlayConfig[] : never;
	reference_lines: Field<ProtocolChartConfigJson, 'referenceLines'> extends unknown[]
		? ReferenceLineConfig[]
		: never;
	chart_height: ChartHeight;
	chart_width: ChartWidth;
}

export interface OverlayConfig {
	chart_type: OverlayChartType;
	y_column: Field<ProtocolOverlayJson, 'yColumn'>;
	aggregation: ChartAggregation;
	y_axis_position: YAxisPosition;
}

export interface ReferenceLineConfig {
	axis: ReferenceAxis;
	value: OptionalField<ProtocolReferenceLineJson, 'value'>;
	label: Field<ProtocolReferenceLineJson, 'label'>;
	color: Field<ProtocolReferenceLineJson, 'color'>;
}

export interface NotificationConfigData {
	method: NotificationMethod;
	recipient: Field<ProtocolNotificationConfigJson, 'recipient'>;
	subscriber_ids: Field<ProtocolNotificationConfigJson, 'subscriberIds'>;
	bot_token: Field<ProtocolNotificationConfigJson, 'botToken'>;
	recipient_source: RecipientSource;
	recipient_column: Field<ProtocolNotificationConfigJson, 'recipientColumn'>;
	input_columns: Field<ProtocolNotificationConfigJson, 'inputColumns'>;
	output_column: Field<ProtocolNotificationConfigJson, 'outputColumn'>;
	message_template: Field<ProtocolNotificationConfigJson, 'messageTemplate'>;
	subject_template: Field<ProtocolNotificationConfigJson, 'subjectTemplate'>;
	batch_size: Field<ProtocolNotificationConfigJson, 'batchSize'>;
}

export interface AIConfigData {
	provider: AIProvider;
	model: Field<ProtocolAIConfigJson, 'model'>;
	input_columns: Field<ProtocolAIConfigJson, 'inputColumns'>;
	output_column: Field<ProtocolAIConfigJson, 'outputColumn'>;
	error_column: Field<ProtocolAIConfigJson, 'errorColumn'>;
	prompt_template: Field<ProtocolAIConfigJson, 'promptTemplate'>;
	batch_size: Field<ProtocolAIConfigJson, 'batchSize'>;
	max_retries: Field<ProtocolAIConfigJson, 'maxRetries'>;
	rate_limit_rpm?: OptionalField<ProtocolAIConfigJson, 'rateLimitRpm'>;
	endpoint_url: Field<ProtocolAIConfigJson, 'endpointUrl'>;
	api_key: Field<ProtocolAIConfigJson, 'apiKey'>;
	temperature: ProtoNumber<ProtocolAIConfigJson['temperature']>;
	max_tokens?: OptionalField<ProtocolAIConfigJson, 'maxTokens'>;
	request_options?: OptionalField<ProtocolAIConfigJson, 'requestOptions'>;
}

// Union type for all possible config types
export type OperationConfig =
	| FilterConfigData
	| SelectConfigData
	| GroupByConfigData
	| SortConfigData
	| RenameConfigData
	| DropConfigData
	| JoinConfigData
	| ExpressionConfigData
	| WithColumnsConfigData
	| DeduplicateConfigData
	| FillNullConfigData
	| ExplodeConfigData
	| PivotConfigData
	| TimeSeriesConfigData
	| StringMethodsConfigData
	| ViewConfigData
	| SampleConfigData
	| LimitConfigData
	| TopKConfigData
	| UnpivotConfigData
	| UnionByNameConfigData
	| ExportConfigData
	| DownloadConfigData
	| PlotConfigData
	| NotificationConfigData
	| AIConfigData;
