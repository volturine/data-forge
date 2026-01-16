// Type definitions for operation configuration objects

export interface FilterCondition {
	column: string;
	operator: string;
	value: string;
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

export interface SortRule {
	column: string;
	descending: boolean;
}

export type SortConfigData = SortRule[];

export interface RenameConfigData {
	column_mapping: Record<string, string>;
}

export interface DropConfigData {
	columns: string[];
}

export interface JoinConfigData {
	how: 'inner' | 'left' | 'right' | 'outer';
	left_on: string[];
	right_on: string[];
}

export interface ExpressionConfigData {
	expression: string;
	column_name: string;
}

export interface DeduplicateConfigData {
	subset: string[] | null;
	keep: string;
}

export interface FillNullConfigData {
	strategy: string;
	columns: string[] | null;
	value?: string | number;
}

export interface ExplodeConfigData {
	columns: string[];
}

export interface PivotConfigData {
	index: string[];
	columns: string;
	values: string;
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
	n?: number;
	fraction?: number;
	shuffle?: boolean;
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

export interface NullCountConfigData extends Record<string, never> {}

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
	| UnpivotConfigData;
