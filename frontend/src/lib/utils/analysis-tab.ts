import type {
	AnalysisTab,
	AnalysisTabDatasource,
	AnalysisTabDatasourceConfig,
	AnalysisTabOutput
} from '$lib/types/analysis';
import { isRecord } from '$lib/utils/json';

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string | null | undefined): boolean {
	return typeof value === 'string' && uuidPattern.test(value);
}

export function generateOutputName(): string {
	return `output-${Date.now()}`;
}

function requireString(value: unknown, field: string): string {
	if (typeof value !== 'string') {
		throw new Error(`${field} is required`);
	}
	const trimmed = value.trim();
	if (!trimmed) {
		throw new Error(`${field} is required`);
	}
	return trimmed;
}

function toSlug(value: string, field: string): string {
	const trimmed = requireString(value, field);
	return trimmed.replace(/\s+/g, '_').toLowerCase();
}

export function buildOutputConfig(args: {
	outputId: string;
	name: string;
	branch: string;
	namespace?: string;
}): AnalysisTabOutput {
	const outputId = requireString(args.outputId, 'outputId');
	const tableName = toSlug(args.name, 'name');
	const branch = requireString(args.branch, 'branch');
	const namespace = requireString(args.namespace ?? 'outputs', 'namespace');
	return {
		result_id: outputId,
		format: 'parquet',
		filename: tableName,
		build_mode: 'full',
		iceberg: {
			namespace,
			table_name: tableName,
			branch
		}
	};
}

export function ensureTabDefaults(tab: AnalysisTab, index: number): AnalysisTab {
	if (!tab.datasource) {
		throw new Error(`Tab ${tab.id ?? index} missing datasource`);
	}
	const datasource = tab.datasource;
	if (!datasource.config || !isRecord(datasource.config)) {
		throw new Error(`Tab ${tab.id ?? index} missing datasource.config`);
	}
	const config = datasource.config;
	const branch = requireString(config.branch, `Tab ${tab.id ?? index} datasource.config.branch`);
	const normalizedDatasource: AnalysisTabDatasource = {
		...datasource,
		config: { ...config, branch }
	};
	if (!tab.output || !isRecord(tab.output)) {
		throw new Error(`Tab ${tab.id ?? index} missing output`);
	}
	const output = tab.output as Partial<AnalysisTabOutput>;
	const outputId =
		typeof output.result_id === 'string' && isUuid(output.result_id) ? output.result_id : null;
	if (!outputId) {
		throw new Error(
			`Tab ${tab.id ?? index} has missing or invalid output.result_id — expected a UUID v4`
		);
	}
	const filename = requireString(output.filename, `Tab ${tab.id ?? index} output.filename`);
	if (
		output.build_mode !== 'full' &&
		output.build_mode !== 'incremental' &&
		output.build_mode !== 'recreate'
	) {
		throw new Error(`Tab ${tab.id ?? index} output.build_mode is required`);
	}
	const icebergRaw = output.iceberg;
	if (!isRecord(icebergRaw)) {
		throw new Error(`Tab ${tab.id ?? index} output.iceberg is required`);
	}
	const namespace = requireString(
		icebergRaw.namespace,
		`Tab ${tab.id ?? index} output.iceberg.namespace`
	);
	const tableName = requireString(
		icebergRaw.table_name,
		`Tab ${tab.id ?? index} output.iceberg.table_name`
	);
	const icebergBranch = requireString(
		icebergRaw.branch,
		`Tab ${tab.id ?? index} output.iceberg.branch`
	);
	const normalizedOutput: AnalysisTabOutput = {
		...output,
		result_id: outputId,
		format: requireString(output.format, `Tab ${tab.id ?? index} output.format`),
		filename,
		build_mode: output.build_mode,
		iceberg: { ...icebergRaw, namespace, table_name: tableName, branch: icebergBranch }
	};
	const normalizedConfig: AnalysisTabDatasourceConfig = normalizedDatasource.config;
	return {
		...tab,
		datasource: { ...normalizedDatasource, config: normalizedConfig },
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
