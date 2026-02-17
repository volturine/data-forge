/**
 * Default configurations for pipeline step types.
 * Centralizes config shape definitions to eliminate defensive $effect blocks in components.
 */

import type { FilterCondition, JoinColumn, PlotConfigData } from '$lib/types/operation-config';

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

export type ChartConfigData = PlotConfigData;

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
	| PlotConfigData
	| NotificationConfigData
	| AIConfigData
	| Record<string, unknown>;

const defaultConfigs: Record<string, StepConfig> = {
	select: { columns: [] } satisfies SelectConfigData,

	drop: { columns: [] } satisfies DropConfigData,

	filter: {
		conditions: [{ column: '', operator: '=', value: '', value_type: 'string' }],
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
		rowLimit: 100
	} satisfies ViewConfigData,

	export: {
		format: 'csv',
		filename: 'export',
		destination: 'download'
	} satisfies ExportConfigData,

	chart: {
		chart_type: 'bar',
		x_column: '',
		y_column: '',
		bins: 10,
		aggregation: 'sum',
		group_column: null
	} satisfies PlotConfigData,

	notification: {
		method: 'email',
		recipient: '',
		subscriber_ids: [],
		bot_token: '',
		recipient_source: 'manual',
		recipient_column: '',
		input_columns: [],
		output_column: 'notification_status',
		message_template: '{{message}}',
		subject_template: 'Notification',
		batch_size: 10,
		timeout_seconds: 20
	} satisfies NotificationConfigData,

	ai: {
		provider: 'ollama',
		model: 'llama2',
		input_columns: [],
		output_column: 'ai_result',
		prompt_template: 'Classify this text: {{text}}',
		batch_size: 10,
		endpoint_url: '',
		api_key: '',
		request_options: null
	} satisfies AIConfigData,

	// Operations that don't need config
	datasource: {},
	sort: {},
	rename: {},
	expression: { expression: '', column_name: '' },
	with_columns: { expressions: [] },
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
	const normalizedType = stepType.startsWith('plot_') ? 'chart' : stepType;
	const defaults = defaultConfigs[normalizedType];
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
	const normalizedType = stepType.startsWith('plot_') ? 'chart' : stepType;
	const defaults = getDefaultConfig(normalizedType);

	if (stepType.startsWith('plot_')) {
		const chartType = stepType.replace('plot_', '');
		const chartConfig = { ...config, chart_type: chartType };
		return { ...defaults, ...chartConfig };
	}
	if (stepType === 'export') {
		const cleaned = { ...config } as Record<string, unknown>;
		delete cleaned.datasource_type;
		delete cleaned.iceberg_options;
		delete cleaned.duckdb_options;
		cleaned.destination = 'download';
		return { ...defaults, ...cleaned };
	}

	// Handle filter-specific normalization for backward compatibility
	if (stepType === 'filter' && Array.isArray(config.conditions)) {
		const conditions = config.conditions as Array<Record<string, unknown>>;
		config.conditions = conditions.map((cond) => ({
			column: cond.column ?? '',
			operator: cond.operator ?? '=',
			value: cond.value ?? '',
			value_type: cond.value_type ?? 'string',
			...(cond.compare_column ? { compare_column: cond.compare_column } : {})
		}));
	}

	const merged = { ...defaults, ...config };

	// Stabilize null/undefined → '' for string fields bound to HTML inputs.
	// HTML inputs convert null to "", which would mutate config and trigger
	// infinite reactivity loops with TanStack Query keys.
	if (normalizedType === 'ai') {
		const ai = merged as Record<string, unknown>;
		if (!Array.isArray(ai.input_columns)) {
			ai.input_columns = [];
		}
		ai.endpoint_url = ai.endpoint_url ?? '';
		ai.api_key = ai.api_key ?? '';
	}
	if (normalizedType === 'notification') {
		const notif = merged as Record<string, unknown>;
		if (!Array.isArray(notif.input_columns)) {
			notif.input_columns = [];
		}
		notif.bot_token = notif.bot_token ?? '';
		notif.recipient = notif.recipient ?? '';
		notif.recipient_source = notif.recipient_source ?? 'manual';
		notif.recipient_column = notif.recipient_column ?? '';
		if (!Array.isArray(notif.subscriber_ids)) {
			notif.subscriber_ids = [];
		}
	}

	return merged;
}
