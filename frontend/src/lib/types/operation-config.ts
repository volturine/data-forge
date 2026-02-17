// Type definitions for operation configuration objects

export type FilterValueType = 'string' | 'number' | 'date' | 'datetime' | 'column' | 'boolean';

export interface FilterCondition {
	column: string;
	operator: string;
	value: string | number | boolean | null;
	value_type: FilterValueType;
	compare_column?: string;
}

export interface FilterConfigData {
	conditions: FilterCondition[];
	logic: 'AND' | 'OR';
}

export interface SelectConfigData {
	columns: string[];
}

export interface Aggregation {
	column: string;
	function: string;
	alias: string;
}

export interface GroupByConfigData {
	groupBy: string[];
	aggregations: Aggregation[];
}

export interface SortConfigData {
	columns: string[];
	descending: boolean[];
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
	values?: string;
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
	seed?: number;
}

export interface LimitConfigData {
	n: number;
}

export interface TopKConfigData {
	column: string;
	k: number;
	descending: boolean;
}

export type NullCountConfigData = Record<string, never>;

export interface ValueCountsConfigData {
	column: string;
	normalize?: boolean;
	sort?: boolean;
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
	chart_type: 'bar' | 'histogram' | 'scatter' | 'line' | 'pie' | 'boxplot';
	x_column: string;
	y_column: string;
	bins: number;
	aggregation: 'sum' | 'mean' | 'count' | 'min' | 'max';
	group_column: string | null;
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
	provider: 'ollama' | 'openai';
	model: string;
	input_columns: string[];
	output_column: string;
	prompt_template: string;
	batch_size: number;
	endpoint_url: string;
	api_key: string;
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
	| NullCountConfigData
	| ValueCountsConfigData
	| UnpivotConfigData
	| UnionByNameConfigData
	| PlotConfigData
	| NotificationConfigData
	| AIConfigData;
