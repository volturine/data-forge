// This file is auto-generated. Do not edit manually. Run 'just generate-step-types' to regenerate.
// Generated from backend/modules/analysis/step_schemas.py

export type CastMapType = 'Int64' | 'Float64' | 'Boolean' | 'String' | 'Utf8' | 'Date' | 'Datetime';

export interface SelectConfig {
	columns?: string[];
	cast_map?: Record<string, CastMapType>;
}

export interface DropConfig {
	columns?: string[];
}

export type FilterValueType = 'string' | 'number' | 'date' | 'datetime' | 'column' | 'boolean';

export interface FilterConditionSchema {
	column: string;
	operator: string;
	value?: string | number | boolean | string[] | null;
	value_type?: FilterValueType;
	compare_column?: string | null;
}

export type FilterLogic = 'AND' | 'OR';

export interface FilterConfig {
	conditions?: FilterConditionSchema[];
	logic?: FilterLogic;
}

export interface AggregationSchema {
	column: string;
	function: string;
	alias: string;
}

export interface GroupByConfig {
	group_by?: string[];
	aggregations?: AggregationSchema[];
}

export interface SortConfig {
	columns?: string[];
	descending?: boolean[] | boolean;
}

export interface RenameConfig {
	column_mapping?: Record<string, string>;
}

export interface ExpressionConfig {
	expression?: string;
	column_name?: string;
}

export type WithColumnsExprType = 'literal' | 'column' | 'udf';

export interface WithColumnsExprSchema {
	name: string;
	type?: WithColumnsExprType;
	value?: string | number | null;
	column?: string | null;
	args?: string[] | null;
	code?: string | null;
	udf_id?: string | null;
}

export interface WithColumnsConfig {
	expressions?: WithColumnsExprSchema[];
}

export interface LimitConfig {
	n?: number;
}

export interface SampleConfig {
	fraction?: number;
	seed?: number | null;
}

export interface TopKConfig {
	column?: string;
	k?: number;
	descending?: boolean;
}

export interface DeduplicateConfig {
	subset?: string[] | null;
	keep?: string;
}

export interface FillNullConfig {
	strategy?: string;
	columns?: string[] | null;
	value?: string | number | null;
	value_type?: string | null;
}

export interface UnpivotConfig {
	id_vars?: string[];
	value_vars?: string[];
	variable_name?: string;
	value_name?: string;
}

export interface ExplodeConfig {
	columns?: string[];
}

export interface PivotConfig {
	index?: string[];
	columns?: string;
	values?: string | null;
	aggregate_function?: string;
}

export interface UnionByNameConfig {
	sources?: string[];
	allow_missing?: boolean;
}

export interface JoinColumnSchema {
	id: string;
	left_column: string;
	right_column: string;
}

export type JoinHow = 'inner' | 'left' | 'right' | 'outer' | 'cross';

export interface JoinConfig {
	how?: JoinHow;
	right_source?: string;
	join_columns?: JoinColumnSchema[];
	right_columns?: string[];
	suffix?: string;
}

export interface ViewConfig {
	rowLimit?: number | null;
}

export interface ExportConfig {
	format?: string;
	filename?: string;
	destination?: string;
}

export interface DownloadConfig {
	format?: string;
	filename?: string;
}

export type OverlayChartType = 'line' | 'area' | 'bar' | 'scatter';

export type YAxisPosition = 'left' | 'right';

export interface OverlaySchema {
	chart_type?: OverlayChartType;
	y_column?: string;
	aggregation?: string;
	y_axis_position?: YAxisPosition;
}

export type ReferenceAxis = 'x' | 'y';

export interface ReferenceLineSchema {
	axis?: ReferenceAxis;
	value?: number | null;
	label?: string;
	color?: string;
}

export type ChartType =
	| 'bar'
	| 'horizontal_bar'
	| 'area'
	| 'heatgrid'
	| 'histogram'
	| 'scatter'
	| 'line'
	| 'pie'
	| 'boxplot';

export type SortDirection = 'asc' | 'desc';

export type StackMode = 'grouped' | 'stacked' | '100%';

export type AxisScale = 'linear' | 'log';

export type LegendPosition = 'top' | 'bottom' | 'left' | 'right' | 'none';

export type ChartHeight = 'small' | 'medium' | 'large' | 'xlarge';

export type ChartWidth = 'normal' | 'wide' | 'full';

export interface ChartConfig {
	chart_type?: ChartType;
	x_column?: string;
	y_column?: string;
	bins?: number;
	aggregation?: string;
	group_column?: string | null;
	group_sort_by?: string | null;
	group_sort_order?: SortDirection;
	group_sort_column?: string | null;
	stack_mode?: StackMode;
	area_opacity?: number;
	date_bucket?: string | null;
	date_ordinal?: string | null;
	pan_zoom_enabled?: boolean;
	selection_enabled?: boolean;
	area_selection_enabled?: boolean;
	sort_by?: string | null;
	sort_order?: SortDirection;
	sort_column?: string | null;
	x_axis_label?: string | null;
	y_axis_label?: string | null;
	y_axis_scale?: AxisScale;
	y_axis_min?: number | null;
	y_axis_max?: number | null;
	display_units?: string;
	decimal_places?: number;
	legend_position?: LegendPosition;
	title?: string | null;
	series_colors?: string[];
	overlays?: OverlaySchema[];
	reference_lines?: ReferenceLineSchema[];
	chart_height?: ChartHeight;
	chart_width?: ChartWidth;
}

export type NotificationMethod = 'email' | 'telegram';

export type RecipientSource = 'manual' | 'column';

export interface NotificationConfig {
	method?: NotificationMethod;
	recipient?: string;
	subscriber_ids?: string[];
	bot_token?: string;
	recipient_source?: RecipientSource;
	recipient_column?: string;
	input_columns?: string[];
	output_column?: string;
	message_template?: string;
	subject_template?: string;
	batch_size?: number;
	timeout_seconds?: number;
}

export type AIProvider = 'ollama' | 'openai' | 'openrouter' | 'huggingface';

export interface AIConfig {
	provider?: AIProvider;
	model?: string;
	input_columns?: string[];
	output_column?: string;
	error_column?: string;
	prompt_template?: string;
	batch_size?: number;
	max_retries?: number;
	rate_limit_rpm?: number | null;
	endpoint_url?: string;
	api_key?: string;
	temperature?: number;
	max_tokens?: number | null;
	request_options?: Record<string, unknown> | null;
}

export interface DatasourceConfig {
	[key: string]: unknown;
}

export interface TimeSeriesConfig {
	column?: string;
	operation_type?: string;
	new_column?: string;
	component?: string | null;
	value?: number | null;
	unit?: string | null;
	column2?: string | null;
}

export interface StringTransformConfig {
	column?: string;
	method?: string;
	new_column?: string;
	start?: number | null;
	end?: number | null;
	pattern?: string | null;
	replacement?: string | null;
	group_index?: number | null;
	delimiter?: string | null;
	index?: number | null;
}
