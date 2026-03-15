// This file is auto-generated. Do not edit manually. Run 'just generate-step-types' to regenerate.
// Generated from backend/modules/analysis/step_schemas.py

export interface SelectConfig {
	columns?: string[];
}

export interface DropConfig {
	columns?: string[];
}

export interface FilterConditionSchema {
	column: string;
	operator: string;
	value?: string | number | boolean | string[] | null;
	value_type?: 'string' | 'number' | 'date' | 'datetime' | 'column' | 'boolean';
	compare_column?: string | null;
}

export interface FilterConfig {
	conditions?: FilterConditionSchema[];
	logic?: 'AND' | 'OR';
}

export interface AggregationSchema {
	column: string;
	function: string;
	alias: string;
}

export interface GroupByConfig {
	groupBy?: string[];
	aggregations?: AggregationSchema[];
}

export interface SortConfig {
	columns?: string[];
	descending?: boolean[];
}

export interface RenameConfig {
	column_mapping?: Record<string, string>;
}

export interface ExpressionConfig {
	expression?: string;
	column_name?: string;
}

export interface WithColumnsExprSchema {
	name: string;
	type?: 'literal' | 'column' | 'udf';
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
	n?: number;
	with_replacement?: boolean;
	shuffle?: boolean;
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

export interface ValueCountsConfig {
	column?: string;
	normalize?: boolean;
	sort?: boolean;
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
	columns?: string[];
	values?: string[];
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

export interface JoinConfig {
	how?: 'inner' | 'left' | 'right' | 'outer' | 'cross';
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

export interface OverlaySchema {
	chart_type?: 'line' | 'area' | 'bar' | 'scatter';
	y_column?: string;
	aggregation?: string;
	y_axis_position?: 'left' | 'right';
}

export interface ReferenceLineSchema {
	axis?: 'x' | 'y';
	value?: number | null;
	label?: string;
	color?: string;
}

export interface ChartConfig {
	chart_type?:
		| 'bar'
		| 'horizontal_bar'
		| 'area'
		| 'heatgrid'
		| 'histogram'
		| 'scatter'
		| 'line'
		| 'pie'
		| 'boxplot';
	x_column?: string;
	y_column?: string;
	bins?: number;
	aggregation?: string;
	group_column?: string | null;
	group_sort_by?: string | null;
	group_sort_order?: 'asc' | 'desc';
	group_sort_column?: string | null;
	stack_mode?: 'grouped' | 'stacked' | '100%';
	area_opacity?: number;
	date_bucket?: string | null;
	date_ordinal?: string | null;
	pan_zoom_enabled?: boolean;
	selection_enabled?: boolean;
	area_selection_enabled?: boolean;
	sort_by?: string | null;
	sort_order?: 'asc' | 'desc';
	sort_column?: string | null;
	x_axis_label?: string | null;
	y_axis_label?: string | null;
	y_axis_scale?: 'linear' | 'log';
	y_axis_min?: number | null;
	y_axis_max?: number | null;
	display_units?: string;
	decimal_places?: number;
	legend_position?: 'top' | 'bottom' | 'left' | 'right' | 'none';
	title?: string | null;
	series_colors?: string[];
	overlays?: OverlaySchema[];
	reference_lines?: ReferenceLineSchema[];
	chart_height?: 'small' | 'medium' | 'large' | 'xlarge';
	chart_width?: 'normal' | 'wide' | 'full';
}

export interface NotificationConfig {
	method?: 'email' | 'telegram';
	recipient?: string;
	subscriber_ids?: string[];
	bot_token?: string;
	recipient_source?: 'manual' | 'column';
	recipient_column?: string;
	input_columns?: string[];
	output_column?: string;
	message_template?: string;
	subject_template?: string;
	batch_size?: number;
	timeout_seconds?: number;
}

export interface AIConfig {
	provider?: 'ollama' | 'openai';
	model?: string;
	input_columns?: string[];
	output_column?: string;
	prompt_template?: string;
	batch_size?: number;
	endpoint_url?: string;
	api_key?: string;
	request_options?: Record<string, unknown> | null;
}

export interface DatasourceConfig {
	[key: string]: unknown;
}

export interface NullCountConfig {
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
