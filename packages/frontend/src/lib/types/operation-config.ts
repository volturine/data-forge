// Type definitions for operation configuration objects

import type {
	AIProvider as StepAIProvider,
	AxisScale,
	CastMapType,
	ChartAggregation,
	ChartHeight,
	ChartType,
	DateBucket,
	DateOrdinal,
	DeduplicateKeep,
	DisplayUnits,
	DurationUnit,
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
	TimeseriesOperationType,
	WithColumnsExprType,
	YAxisPosition
} from '$lib/types/step-schemas.generated';

export type FilterValueType = StepFilterValueType;

export interface FilterCondition {
	column: string;
	operator: FilterOperator;
	value: string | number | boolean | string[] | null;
	value_type: FilterValueType;
	compare_column?: string;
}

export interface FilterConfigData {
	conditions: FilterCondition[];
	logic: FilterLogic;
}

export interface SelectConfigData {
	columns: string[];
	cast_map?: Record<string, CastMapType>;
}

export interface Aggregation {
	column: string;
	function: GroupByAggregationFunction;
	alias: string;
}

export interface GroupByConfigData {
	group_by: string[];
	aggregations: Aggregation[];
}

export interface SortConfigData {
	columns: string[];
	descending: boolean[] | boolean;
}

export interface RenameConfigData {
	column_mapping: Record<string, string>;
}

export interface DropConfigData {
	columns: string[];
}

export interface JoinColumn {
	id: string;
	left_column: string;
	right_column: string;
}

export interface JoinConfigData {
	how: JoinHow;
	right_source?: string;
	join_columns: JoinColumn[];
	right_columns: string[];
	suffix: string;
}

export interface ExpressionConfigData {
	expression: string;
	column_name: string;
}

export interface WithColumnsExpr {
	name: string;
	type: WithColumnsExprType;
	value?: string | number | null;
	column?: string | null;
	args?: string[] | null;
	code?: string | null;
	udf_id?: string | null;
}

export interface WithColumnsConfigData {
	expressions: WithColumnsExpr[];
}

export interface DeduplicateConfigData {
	subset: string[] | null;
	keep: DeduplicateKeep;
}

export interface FillNullConfigData {
	strategy: FillNullStrategy;
	columns: string[] | null;
	value?: string | number;
	value_type?: CastMapType;
}

export interface ExplodeConfigData {
	columns: string[];
}

export interface PivotConfigData {
	index: string[];
	columns: string;
	values?: string | null;
	aggregate_function: PivotAggregateFunction;
}

export interface TimeSeriesConfigData {
	column: string;
	operation_type: TimeseriesOperationType;
	new_column: string;
	component?: TimeComponent;
	value?: number;
	unit?: DurationUnit;
	column2?: string;
}

export interface StringMethodsConfigData {
	column: string;
	method: StringTransformMethod;
	new_column: string;
	start?: number;
	end?: number | null;
	pattern?: string;
	replacement?: string;
	group_index?: number;
	delimiter?: string;
	index?: number;
}

export interface ViewConfigData {
	rowLimit: number;
}

export interface SampleConfigData {
	fraction?: number;
	seed?: number | null;
}

export interface LimitConfigData {
	n: number;
}

export interface TopKConfigData {
	column: string;
	k: number;
	descending: boolean;
}

export interface UnpivotConfigData {
	index?: string[];
	on?: string[];
	variable_name?: string;
	value_name?: string;
}

export interface UnionByNameConfigData {
	sources: string[];
	allow_missing: boolean;
}

export interface PlotConfigData {
	chart_type: ChartType;
	x_column: string;
	y_column: string;
	bins: number;
	aggregation: ChartAggregation;
	group_column: string | null;
	group_sort_by: GroupSortBy | null;
	group_sort_order: SortDirection;
	group_sort_column: string | null;
	stack_mode: StackMode;
	area_opacity: number;
	date_bucket: DateBucket | null;
	date_ordinal: DateOrdinal | null;
	pan_zoom_enabled: boolean;
	selection_enabled: boolean;
	area_selection_enabled: boolean;
	sort_by: SortBy | null;
	sort_order: SortDirection;
	sort_column: string | null;
	x_axis_label: string | null;
	y_axis_label: string | null;
	y_axis_scale: AxisScale;
	y_axis_min: number | null;
	y_axis_max: number | null;
	display_units: DisplayUnits;
	decimal_places: number;
	legend_position: LegendPosition;
	title: string | null;
	series_colors: string[];
	overlays: OverlayConfig[];
	reference_lines: ReferenceLineConfig[];
	chart_height: ChartHeight;
}

export interface OverlayConfig {
	chart_type: OverlayChartType;
	y_column: string;
	aggregation: ChartAggregation;
	y_axis_position: YAxisPosition;
}

export interface ReferenceLineConfig {
	axis: ReferenceAxis;
	value: number | null;
	label: string;
	color: string;
}

export interface NotificationConfigData {
	method: NotificationMethod;
	recipient: string;
	subscriber_ids: string[];
	bot_token: string;
	recipient_source: RecipientSource;
	recipient_column: string;
	input_columns: string[];
	output_column: string;
	message_template: string;
	subject_template: string;
	batch_size: number;
}

export interface AIConfigData {
	provider: StepAIProvider;
	model: string;
	input_columns: string[];
	output_column: string;
	error_column: string;
	prompt_template: string;
	batch_size: number;
	max_retries: number;
	rate_limit_rpm?: number | null;
	endpoint_url: string;
	api_key: string;
	temperature: number;
	max_tokens?: number | null;
	request_options?: Record<string, unknown> | null;
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
	| PlotConfigData
	| NotificationConfigData
	| AIConfigData;
