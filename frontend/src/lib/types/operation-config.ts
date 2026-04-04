// Type definitions for operation configuration objects

export type FilterValueType = 'string' | 'number' | 'date' | 'datetime' | 'column' | 'boolean';

export interface FilterCondition {
	column: string;
	operator: string;
	value: string | number | boolean | string[] | null;
	value_type: FilterValueType;
	compare_column?: string;
}

export interface FilterConfigData {
	conditions: FilterCondition[];
	logic: 'AND' | 'OR';
}

export interface SelectConfigData {
	columns: string[];
	cast_map?: Record<string, string>;
}

export interface Aggregation {
	column: string;
	function: string;
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
	how: 'inner' | 'left' | 'right' | 'outer' | 'cross';
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
	type: 'literal' | 'column' | 'udf';
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
	keep: string;
}

export interface FillNullConfigData {
	strategy: string;
	columns: string[] | null;
	value?: string | number;
	value_type?: string;
}

export interface ExplodeConfigData {
	columns: string[];
}

export interface PivotConfigData {
	index: string[];
	columns: string;
	values?: string | null;
	aggregate_function: string;
}

export interface TimeSeriesConfigData {
	column: string;
	operation_type: string;
	new_column: string;
	component?: string;
	value?: number;
	unit?: string;
	column2?: string;
}

export interface StringMethodsConfigData {
	column: string;
	method: string;
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
	chart_type:
		| 'bar'
		| 'horizontal_bar'
		| 'area'
		| 'heatgrid'
		| 'histogram'
		| 'scatter'
		| 'line'
		| 'pie'
		| 'boxplot';
	x_column: string;
	y_column: string;
	bins: number;
	aggregation:
		| 'sum'
		| 'mean'
		| 'count'
		| 'min'
		| 'max'
		| 'median'
		| 'std'
		| 'variance'
		| 'unique_count';
	group_column: string | null;
	group_sort_by: 'name' | 'value' | 'custom' | null;
	group_sort_order: 'asc' | 'desc';
	group_sort_column: string | null;
	stack_mode: 'grouped' | 'stacked' | '100%';
	area_opacity: number;
	date_bucket: 'exact' | 'year' | 'quarter' | 'month' | 'week' | 'day' | 'hour' | null;
	date_ordinal: 'day_of_week' | 'month_of_year' | 'quarter_of_year' | null;
	pan_zoom_enabled: boolean;
	selection_enabled: boolean;
	area_selection_enabled: boolean;
	sort_by: 'x' | 'y' | 'custom' | null;
	sort_order: 'asc' | 'desc';
	sort_column: string | null;
	x_axis_label: string | null;
	y_axis_label: string | null;
	y_axis_scale: 'linear' | 'log';
	y_axis_min: number | null;
	y_axis_max: number | null;
	display_units: '' | 'K' | 'M' | 'B' | '%';
	decimal_places: number;
	legend_position: 'top' | 'bottom' | 'left' | 'right' | 'none';
	title: string | null;
	series_colors: string[];
	overlays: OverlayConfig[];
	reference_lines: ReferenceLineConfig[];
	chart_height: 'small' | 'medium' | 'large' | 'xlarge';
}

export interface OverlayConfig {
	chart_type: 'line' | 'area' | 'bar' | 'scatter';
	y_column: string;
	aggregation:
		| 'sum'
		| 'mean'
		| 'count'
		| 'min'
		| 'max'
		| 'median'
		| 'std'
		| 'variance'
		| 'unique_count';
	y_axis_position: 'left' | 'right';
}

export interface ReferenceLineConfig {
	axis: 'x' | 'y';
	value: number | null;
	label: string;
	color: string;
}

export interface NotificationConfigData {
	method: 'email' | 'telegram';
	recipient: string;
	subscriber_ids: string[];
	bot_token: string;
	recipient_source: 'manual' | 'column';
	recipient_column: string;
	input_columns: string[];
	output_column: string;
	message_template: string;
	subject_template: string;
	batch_size: number;
	timeout_seconds: number;
}

export interface AIConfigData {
	provider: 'ollama' | 'openai' | 'openrouter' | 'huggingface';
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
