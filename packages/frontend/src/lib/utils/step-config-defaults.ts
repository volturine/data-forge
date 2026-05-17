/**
 * Default configurations for pipeline step types.
 * Centralizes config shape definitions to eliminate defensive $effect blocks in components.
 */

import type {
	PlotConfigData,
	TopKConfigData,
	SampleConfigData,
	PivotConfigData
} from '$lib/types/operation-config';
import type {
	SelectConfig,
	DropConfig,
	FilterConfig,
	GroupByConfig,
	JoinConfig,
	UnionByNameConfig,
	UnpivotConfig,
	ExplodeConfig,
	LimitConfig,
	ViewConfig,
	ExportConfig,
	DownloadConfig,
	NotificationConfig,
	AIConfig
} from '$lib/types/step-schemas.generated';
import {
	chartTypeForStep,
	isChartStepType,
	normalizePipelineStepType
} from '$lib/types/pipeline-step';
import { cloneJson } from '$lib/utils/json';

// ChartConfigData re-uses the richer PlotConfigData type from operation-config.
export type ChartConfigData = PlotConfigData;

export type StepConfig =
	| SelectConfig
	| DropConfig
	| FilterConfig
	| GroupByConfig
	| JoinConfig
	| UnionByNameConfig
	| UnpivotConfig
	| ExplodeConfig
	| PivotConfigData
	| SampleConfigData
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
		group_by: [],
		aggregations: []
	} satisfies GroupByConfig,

	join: {
		how: 'inner',
		right_source: '',
		join_columns: [],
		right_columns: [],
		suffix: '_right'
	} satisfies JoinConfig,

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
		columns: '',
		values: null,
		aggregate_function: 'first'
	} satisfies PivotConfigData,

	sample: {
		fraction: 0.5,
		seed: null
	} satisfies SampleConfigData,

	limit: {
		n: 100
	} satisfies LimitConfig,

	topk: {
		column: '',
		k: 10,
		descending: false
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
		batch_size: 10
	} satisfies NotificationConfig,

	ai: {
		provider: 'ollama',
		model: 'llama3.2',
		input_columns: [],
		output_column: 'ai_result',
		error_column: 'ai_error',
		prompt_template: 'Classify this text: {{text}}',
		batch_size: 10,
		max_retries: 3,
		rate_limit_rpm: null,
		endpoint_url: '',
		api_key: '',
		temperature: 0.7,
		max_tokens: null,
		request_options: null
	} satisfies AIConfig,

	// Operations that don't need config
	datasource: {},
	sort: {},
	rename: {},
	expression: { expression: '', column_name: '' },
	with_columns: { expressions: [] },
	fill_null: {},
	deduplicate: { subset: null, keep: 'first' },
	string_transform: {},
	timeseries: {}
};

function stripUiConfigFields(config: Record<string, unknown>): Record<string, unknown> {
	const next = cloneJson(config);
	delete next.description;
	return next;
}

/**
 * Get default config for a step type.
 * Returns a fresh copy to avoid reference sharing between steps.
 */
export function getDefaultConfig(stepType: string): StepConfig {
	const normalizedType = normalizePipelineStepType(stepType);
	const defaults = defaultConfigs[normalizedType];
	return defaults ? cloneJson(defaults) : {};
}

/**
 * Normalize step config without inventing missing values.
 */
export function normalizeConfig(stepType: string, config: Record<string, unknown>): StepConfig {
	const normalizedType = normalizePipelineStepType(stepType);
	const cleaned =
		normalizedType in defaultConfigs ? stripUiConfigFields(config) : cloneJson(config);

	if (isChartStepType(stepType)) {
		const chartAliasType = chartTypeForStep(stepType);
		if (chartAliasType) {
			return { ...cleaned, chart_type: chartAliasType };
		}
	}

	return cleaned;
}
