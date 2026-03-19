import type { AnalysisTab, AnalysisTabDatasource, AnalysisTabOutput } from '$lib/types/analysis';

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string | null | undefined): boolean {
	return typeof value === 'string' && uuidPattern.test(value);
}

const defaultBranch = 'master';
const defaultNamespace = 'outputs';
const defaultBuildMode = 'full';
const defaultFormat = 'parquet';
const outputNameFallback = 'export';

function cleanBranch(value: unknown): string {
	const trimmed = typeof value === 'string' ? value.trim() : '';
	return trimmed || defaultBranch;
}

function toSlug(value: string): string {
	return value.trim().replace(/\s+/g, '_').toLowerCase() || outputNameFallback;
}

export function buildOutputConfig(args: {
	outputId: string;
	name?: string | null;
	branch?: string | null;
}): AnalysisTabOutput {
	const outputId = args.outputId;
	const name = args.name ?? outputNameFallback;
	const tableName = toSlug(name);
	const branch = cleanBranch(args.branch);
	return {
		result_id: outputId,
		format: defaultFormat,
		filename: tableName,
		build_mode: defaultBuildMode,
		iceberg: {
			namespace: defaultNamespace,
			table_name: tableName,
			branch
		}
	};
}

export function ensureTabDefaults(tab: AnalysisTab, index: number): AnalysisTab {
	const fallbackDatasource: AnalysisTabDatasource = {
		id: '',
		analysis_tab_id: null,
		config: { branch: defaultBranch }
	};
	const datasource = tab.datasource ?? fallbackDatasource;
	const config = datasource.config ?? { branch: defaultBranch };
	const branch = cleanBranch((config as Record<string, unknown>).branch);
	const normalizedDatasource: AnalysisTabDatasource = {
		...datasource,
		config: { ...config, branch }
	};
	const output = (tab.output ?? {}) as AnalysisTabOutput;
	const outputId =
		typeof output.result_id === 'string' && isUuid(output.result_id) ? output.result_id : null;
	if (!outputId) {
		throw new Error(
			`Tab ${tab.id ?? index} has missing or invalid output.result_id — expected a UUID v4`
		);
	}
	const name =
		typeof tab.name === 'string' && tab.name.trim() ? tab.name.trim() : `Source ${index + 1}`;
	const defaults = buildOutputConfig({ outputId, name, branch });
	const icebergRaw = output.iceberg;
	const iceberg =
		icebergRaw && typeof icebergRaw === 'object' && !Array.isArray(icebergRaw)
			? { ...(defaults.iceberg as Record<string, unknown>), ...icebergRaw }
			: defaults.iceberg;
	const normalizedOutput: AnalysisTabOutput = {
		...defaults,
		...output,
		result_id: defaults.result_id,
		iceberg
	};
	return {
		...tab,
		datasource: normalizedDatasource,
		output: normalizedOutput
	};
}

export type PipelineValidationError = {
	tabId: string;
	field: string;
	message: string;
};

export function validatePipelineTabs(tabs: AnalysisTab[]): PipelineValidationError[] {
	const errors: PipelineValidationError[] = [];
	const outputByTabId = new Map<string, string>();
	for (const tab of tabs) {
		const outputId = tab.output?.result_id;
		if (!tab.id || !outputId) continue;
		outputByTabId.set(String(tab.id), String(outputId));
	}

	for (const tab of tabs) {
		const tabId = tab.id ? String(tab.id) : 'unknown';
		const datasource = tab.datasource;
		if (!datasource) {
			errors.push({
				tabId,
				field: 'datasource',
				message: `Tab ${tabId} missing datasource configuration`
			});
			continue;
		}
		if (!datasource.id) {
			errors.push({
				tabId,
				field: 'datasource.id',
				message: `Tab ${tabId} missing datasource.id`
			});
		}

		const output = tab.output;
		if (!output) {
			errors.push({
				tabId,
				field: 'output',
				message: `Tab ${tabId} missing output configuration`
			});
			continue;
		}
		if (!output.result_id) {
			errors.push({
				tabId,
				field: 'output.result_id',
				message: `Tab ${tabId} missing output.result_id`
			});
		}

		const analysisTabId = datasource.analysis_tab_id;
		if (!analysisTabId) continue;
		const upstreamOutputId = outputByTabId.get(String(analysisTabId));
		if (!upstreamOutputId) {
			errors.push({
				tabId,
				field: 'datasource.analysis_tab_id',
				message: `Tab ${tabId} references missing upstream tab output`
			});
			continue;
		}
		if (datasource.id !== upstreamOutputId) {
			errors.push({
				tabId,
				field: 'datasource.id',
				message: `Tab ${tabId} datasource.id must match upstream result_id`
			});
		}
	}
	return errors;
}

export function formatPipelineErrors(errors: PipelineValidationError[]): string {
	if (!errors.length) return '';
	const [first, ...rest] = errors;
	const suffix = rest.length ? ` (+${rest.length} more)` : '';
	return `${first.message}${suffix}`;
}
