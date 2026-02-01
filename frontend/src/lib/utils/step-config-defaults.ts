/**
 * Default configurations for pipeline step types.
 * Centralizes config shape definitions to eliminate defensive $effect blocks in components.
 */

import type { FilterCondition, JoinColumn } from '$lib/types/operation-config';

export interface SelectConfigData {
	columns: string[];
}

export interface DropConfigData {
	columns: string[];
}

export interface FilterConfigData {
	conditions: FilterCondition[];
	logic: 'AND' | 'OR';
}

export interface GroupByConfigData {
	groupBy: string[];
	aggregations: Array<{
		column: string;
		function: string;
		alias: string;
	}>;
}

export interface JoinConfigData {
	how: 'inner' | 'left' | 'right' | 'outer' | 'cross';
	right_source: string;
	join_columns: JoinColumn[];
	right_columns: string[];
	suffix: string;
}

export interface UnionByNameConfigData {
	sources: string[];
	allow_missing: boolean;
}

export interface ValueCountsConfigData {
	column: string;
	sort: boolean;
}

export interface UnpivotConfigData {
	id_vars: string[];
	value_vars: string[];
	variable_name: string;
	value_name: string;
}

export interface ExplodeConfigData {
	columns: string[];
}

export interface PivotConfigData {
	index: string[];
	columns: string[];
	values: string[];
	aggregate_function: string;
}

export interface SampleConfigData {
	n: number;
	with_replacement: boolean;
	shuffle: boolean;
	seed: number | null;
}

export interface LimitConfigData {
	n: number;
}

export interface TopKConfigData {
	by: string;
	k: number;
	reverse: boolean;
}

export interface ViewConfigData {
	rowLimit: number | null;
}

export interface ExportConfigData {
	format: string;
	filename: string;
	destination: string;
}

export type StepConfig =
	| SelectConfigData
	| DropConfigData
	| FilterConfigData
	| GroupByConfigData
	| JoinConfigData
	| UnionByNameConfigData
	| ValueCountsConfigData
	| UnpivotConfigData
	| ExplodeConfigData
	| PivotConfigData
	| SampleConfigData
	| LimitConfigData
	| TopKConfigData
	| ViewConfigData
	| ExportConfigData
	| Record<string, unknown>;

const defaultConfigs: Record<string, StepConfig> = {
	select: { columns: [] } satisfies SelectConfigData,

	drop: { columns: [] } satisfies DropConfigData,

	filter: {
		conditions: [{ column: '', operator: '=', value: '' }],
		logic: 'AND'
	} satisfies FilterConfigData,

	groupby: {
		groupBy: [],
		aggregations: []
	} satisfies GroupByConfigData,

	join: {
		how: 'inner',
		right_source: '',
		join_columns: [],
		right_columns: [],
		suffix: '_right'
	} satisfies JoinConfigData,

	union_by_name: {
		sources: [],
		allow_missing: true
	} satisfies UnionByNameConfigData,

	value_counts: {
		column: '',
		sort: true
	} satisfies ValueCountsConfigData,

	unpivot: {
		id_vars: [],
		value_vars: [],
		variable_name: 'variable',
		value_name: 'value'
	} satisfies UnpivotConfigData,

	explode: {
		columns: []
	} satisfies ExplodeConfigData,

	pivot: {
		index: [],
		columns: [],
		values: [],
		aggregate_function: 'first'
	} satisfies PivotConfigData,

	sample: {
		n: 1000,
		with_replacement: false,
		shuffle: true,
		seed: null
	} satisfies SampleConfigData,

	limit: {
		n: 100
	} satisfies LimitConfigData,

	topk: {
		by: '',
		k: 10,
		reverse: false
	} satisfies TopKConfigData,

	view: {
		rowLimit: null
	} satisfies ViewConfigData,

	export: {
		format: 'csv',
		filename: 'export',
		destination: 'download'
	} satisfies ExportConfigData,

	// Operations that don't need config
	datasource: {},
	sort: {},
	rename: {},
	expression: { expression: '', column_name: '' },
	with_columns: {},
	fill_null: {},
	deduplicate: {},
	string_transform: {},
	timeseries: {},
	null_count: {}
};

/**
 * Get default config for a step type.
 * Returns a fresh copy to avoid reference sharing between steps.
 */
export function getDefaultConfig(stepType: string): StepConfig {
	const defaults = defaultConfigs[stepType];
	if (!defaults) {
		return {};
	}
	// Deep clone to prevent shared references
	return JSON.parse(JSON.stringify(defaults));
}

/**
 * Ensure a config has all required fields by merging with defaults.
 * Used when loading saved analyses to handle backward compatibility.
 * Preserves all existing config fields while adding any missing defaults.
 */
export function normalizeConfig(stepType: string, config: Record<string, unknown>): StepConfig {
	const defaults = getDefaultConfig(stepType);
	return { ...defaults, ...config };
}
