/**
 * Default configurations for pipeline step types.
 * Centralizes config shape definitions to eliminate defensive $effect blocks in components.
 */

import type { PlotConfigData } from '$lib/types/operation-config';
import type {
	SelectConfig,
	DropConfig,
	FilterConfig,
	GroupByConfig,
	UnionByNameConfig,
	UnpivotConfig,
	ExplodeConfig,
	PivotConfig,
	SampleConfig,
	LimitConfig,
	ViewConfig,
	ExportConfig,
	DownloadConfig,
	NotificationConfig,
	AIConfig
} from '$lib/types/step-schemas.generated';

// Frontend-only type: TopK uses different field names than the Pydantic model.
// The backend uses `column`/`descending`; the frontend UI uses `by`/`reverse`.
export interface TopKConfigData {
	by: string;
	k: number;
	reverse: boolean;
}

// ChartConfigData re-uses the richer PlotConfigData type from operation-config.
export type ChartConfigData = PlotConfigData;

export type StepConfig =
	| SelectConfig
	| DropConfig
	| FilterConfig
	| GroupByConfig
	| UnionByNameConfig
	| UnpivotConfig
	| ExplodeConfig
	| PivotConfig
	| SampleConfig
	| LimitConfig
	| TopKConfigData
	| ViewConfig
	| ExportConfig
	| DownloadConfig
	| PlotConfigData
	| NotificationConfig
	| AIConfig
	| Record<string, unknown>;

const defaultConfigs: Record<string, StepConfig> = {
	select: { columns: [], cast_map: {} } satisfies SelectConfig,

	drop: { columns: [] } satisfies DropConfig,

	filter: {
		conditions: [{ column: '', operator: '=', value: '', value_type: 'string' }],
		logic: 'AND'
	} satisfies FilterConfig,

	groupby: {
		groupBy: [],
		aggregations: []
	} satisfies GroupByConfig,

	join: {
		how: 'inner',
		right_source: '',
		join_columns: [],
		right_columns: [],
		suffix: '_right'
	} as Record<string, unknown>,

	union_by_name: {
		sources: [],
		allow_missing: true
	} satisfies UnionByNameConfig,

	unpivot: {
		id_vars: [],
		value_vars: [],
		variable_name: 'variable',
		value_name: 'value'
	} satisfies UnpivotConfig,

	explode: {
		columns: []
	} satisfies ExplodeConfig,

	pivot: {
		index: [],
		columns: [],
		values: [],
		aggregate_function: 'first'
	} satisfies PivotConfig,

	sample: {
		n: 1000,
		with_replacement: false,
		shuffle: true,
		seed: null
	} satisfies SampleConfig,

	limit: {
		n: 100
	} satisfies LimitConfig,

	topk: {
		by: '',
		k: 10,
		reverse: false
	} satisfies TopKConfigData,

	view: {
		rowLimit: 100
	} satisfies ViewConfig,

	export: {
		format: 'csv',
		filename: 'export',
		destination: 'download'
	} satisfies ExportConfig,

	download: {
		format: 'csv',
		filename: 'download'
	} satisfies DownloadConfig,

	chart: {
		chart_type: 'bar',
		x_column: '',
		y_column: '',
		bins: 10,
		aggregation: 'sum',
		group_column: null,
		group_sort_by: null,
		group_sort_order: 'asc',
		group_sort_column: null,
		stack_mode: 'grouped',
		area_opacity: 0.35,
		date_bucket: null,
		date_ordinal: null,
		pan_zoom_enabled: false,
		selection_enabled: false,
		area_selection_enabled: false,
		sort_by: null,
		sort_order: 'asc',
		sort_column: null,
		x_axis_label: '',
		y_axis_label: '',
		y_axis_scale: 'linear',
		y_axis_min: null,
		y_axis_max: null,
		display_units: '',
		decimal_places: 2,
		legend_position: 'right',
		title: '',
		series_colors: [],
		overlays: [],
		reference_lines: [],
		chart_height: 'medium'
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
	} satisfies NotificationConfig,

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
	} satisfies AIConfig,

	// Operations that don't need config
	datasource: {},
	sort: {},
	rename: {},
	expression: { expression: '', column_name: '' },
	with_columns: { expressions: [] },
	fill_null: {},
	deduplicate: {},
	string_transform: {},
	timeseries: {}
};

/**
 * Get default config for a step type.
 * Returns a fresh copy to avoid reference sharing between steps.
 */
export function getDefaultConfig(stepType: string): StepConfig {
	const normalizedType = stepType.startsWith('plot_') ? 'chart' : stepType;
	const defaults = defaultConfigs[normalizedType];
	return defaults ? JSON.parse(JSON.stringify(defaults)) : {};
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
		delete cleaned.iceberg_options;
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
	if (normalizedType === 'chart') {
		const chart = merged as Record<string, unknown>;
		chart.x_axis_label = chart.x_axis_label ?? '';
		chart.y_axis_label = chart.y_axis_label ?? '';
		chart.title = chart.title ?? '';
		if (!Array.isArray(chart.overlays)) {
			chart.overlays = [];
		}
		if (!Array.isArray(chart.reference_lines)) {
			chart.reference_lines = [];
		}
	}

	return merged;
}
