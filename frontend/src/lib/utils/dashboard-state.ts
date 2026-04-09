import type {
	AnalysisDateRangeValue,
	AnalysisVariableDefinition,
	DashboardDefinition,
	DashboardLayoutItem,
	DashboardWidget,
	DashboardWidgetType
} from '$lib/types/analysis';

function nextId(prefix: string): string {
	const token =
		typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
			? crypto.randomUUID()
			: `${Date.now()}-${Math.random().toString(16).slice(2)}`;
	return `${prefix}-${token}`;
}

export function createVariableDraft(index: number): AnalysisVariableDefinition {
	return {
		id: `variable_${index + 1}`,
		label: `Variable ${index + 1}`,
		type: 'string',
		default_value: '',
		required: true,
		options: [],
		option_source: null
	};
}

export function createDashboardDraft(index: number): DashboardDefinition {
	return {
		id: `dashboard_${index + 1}`,
		name: `Dashboard ${index + 1}`,
		description: null,
		layout: [],
		widgets: []
	};
}

export function createWidgetDraft(
	type: DashboardWidgetType,
	tabId: string | null,
	index: number
): { widget: DashboardWidget; layout: DashboardLayoutItem } {
	const id = nextId(`widget-${type}`);
	const title = `${type.replace('_', ' ')} ${index + 1}`;
	const widget: DashboardWidget = {
		id,
		type,
		title,
		description: null,
		source_tab_id: type === 'text_header' ? null : tabId,
		config:
			type === 'dataset_preview'
				? { page_size: 25, searchable: true }
				: type === 'chart'
					? { chart_type: 'bar', x_column: '', y_column: '', aggregation: 'sum' }
					: type === 'metric_kpi'
						? { label: 'KPI', aggregation: 'count', column: '' }
						: { text: 'Section title', level: 2 }
	};
	return {
		widget,
		layout: {
			widget_id: id,
			x: 0,
			y: index * 2,
			w: type === 'metric_kpi' ? 4 : 6,
			h: type === 'text_header' ? 1 : 2
		}
	};
}

function defaultStateValue(variable: AnalysisVariableDefinition): unknown {
	return variable.default_value;
}

function parseDateRange(value: string | null): AnalysisDateRangeValue | null {
	if (!value) return null;
	const [start, end] = value.split('..');
	if (!start || !end) return null;
	return { start, end };
}

export function parseDashboardVariableState(
	variables: AnalysisVariableDefinition[],
	search: URLSearchParams
): Record<string, unknown> {
	const state: Record<string, unknown> = {};
	for (const variable of variables) {
		const raw = search.get(variable.id);
		if (raw === null) {
			state[variable.id] = defaultStateValue(variable);
			continue;
		}
		if (variable.type === 'number') {
			const parsed = Number(raw);
			state[variable.id] = Number.isFinite(parsed) ? parsed : variable.default_value;
			continue;
		}
		if (variable.type === 'boolean') {
			state[variable.id] = raw === 'true';
			continue;
		}
		if (variable.type === 'multi_select') {
			state[variable.id] = raw ? raw.split(',').filter(Boolean) : [];
			continue;
		}
		if (variable.type === 'date_range') {
			state[variable.id] = parseDateRange(raw) ?? variable.default_value;
			continue;
		}
		state[variable.id] = raw;
	}
	return state;
}

export function serializeDashboardVariableState(
	variables: AnalysisVariableDefinition[],
	state: Record<string, unknown>
): URLSearchParams {
	const params = new URLSearchParams();
	for (const variable of variables) {
		const value = state[variable.id] ?? variable.default_value;
		if (variable.type === 'multi_select' && Array.isArray(value)) {
			params.set(variable.id, value.map((item) => String(item)).join(','));
			continue;
		}
		if (variable.type === 'date_range' && value && typeof value === 'object') {
			const range = value as AnalysisDateRangeValue;
			params.set(variable.id, `${range.start}..${range.end}`);
			continue;
		}
		params.set(variable.id, String(value));
	}
	return params;
}

export function getAffectedWidgetIds(
	dependencies: Record<string, string[]>,
	changedVariableId: string
): string[] {
	return Object.entries(dependencies)
		.filter(([, variableIds]) => variableIds.includes(changedVariableId))
		.map(([widgetId]) => widgetId);
}
