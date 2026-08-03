import type {
	AnalysisTab,
	AnalysisTabDatasourceConfig,
	AnalysisTabOutput,
	PipelineStep
} from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import { applySteps } from '$lib/utils/pipeline';
import { isRecord } from '$lib/utils/json';
import { normalizeConfig } from '$lib/utils/step-config-defaults';

type PipelineDatasource = {
	id: string;
	analysis_tab_id: string | null;
	source_type?: DataSource['source_type'] | 'analysis';
	config: AnalysisTabDatasourceConfig;
};

type PipelineTab = {
	id: string;
	name: string;
	datasource: PipelineDatasource;
	output: AnalysisTabOutput;
	steps: PipelineStep[];
};

export type AnalysisPipelinePayload = {
	analysis_id: string;
	tabs: PipelineTab[];
};

function toDatasourceConfig(config: Record<string, unknown>): AnalysisTabDatasourceConfig {
	const branchRaw = config.branch;
	if (typeof branchRaw !== 'string' || !branchRaw.trim()) {
		throw new Error('datasource config.branch is required');
	}
	const branch = branchRaw.trim();
	return { ...config, branch };
}

function mergeDatasourceConfig(
	persisted: Record<string, unknown>,
	overrides: Record<string, unknown>
): AnalysisTabDatasourceConfig {
	return normalizeSnapshotConfig({ ...persisted, ...overrides });
}

/**
 * Normalize time-travel fields into compute-ready snapshot fields.
 * Strips `time_travel_snapshot_id`, `time_travel_snapshot_timestamp_ms`,
 * and `time_travel_ui` from the config, mapping the first two into
 * `snapshot_id` / `snapshot_timestamp_ms` for the engine.
 */
export function normalizeSnapshotConfig(
	config: Record<string, unknown>
): AnalysisTabDatasourceConfig {
	const typedConfig = toDatasourceConfig(config);
	const {
		time_travel_snapshot_id,
		time_travel_snapshot_timestamp_ms,
		time_travel_ui: _ui,
		branches: _branches,
		...rest
	} = typedConfig;
	const normalized: AnalysisTabDatasourceConfig = { ...rest, branch: rest.branch };
	if (time_travel_snapshot_id != null) {
		normalized.snapshot_id = time_travel_snapshot_id;
		if (time_travel_snapshot_timestamp_ms != null) {
			normalized.snapshot_timestamp_ms = time_travel_snapshot_timestamp_ms;
		}
	}
	return normalized;
}

function toPipelineDatasource(args: {
	analysisId: string;
	datasource: AnalysisTab['datasource'];
	datasourceMap: Map<string, DataSource>;
	outputById: Map<string, string>;
}): PipelineDatasource {
	const config = normalizeSnapshotConfig(args.datasource.config);
	if (args.datasource.analysis_tab_id) {
		return {
			id: args.datasource.id,
			analysis_tab_id: args.datasource.analysis_tab_id,
			source_type: 'analysis',
			config
		};
	}
	const upstreamTabId = args.outputById.get(args.datasource.id);
	if (upstreamTabId) {
		return {
			id: args.datasource.id,
			analysis_tab_id: upstreamTabId,
			source_type: 'analysis',
			config
		};
	}
	const ds = args.datasourceMap.get(args.datasource.id);
	if (!ds) {
		throw new Error(`datasource ${args.datasource.id} metadata is required`);
	}
	if (!isRecord(ds.config)) {
		throw new Error(`datasource ${ds.id} config is invalid`);
	}
	return {
		id: args.datasource.id,
		analysis_tab_id: null,
		source_type: ds.source_type,
		config: mergeDatasourceConfig(ds.config, config)
	};
}

export function buildAnalysisPipelinePayload(
	analysisId: string,
	tabs: AnalysisTab[],
	datasources: DataSource[]
): AnalysisPipelinePayload | null {
	if (!analysisId) return null;
	if (!tabs.length) return null;

	const datasourceMap = new Map(datasources.map((ds) => [ds.id, ds]));
	const missing: string[] = [];
	const outputByTabId = new Map<string, string>();
	const outputById = new Map<string, string>();
	for (const tab of tabs) {
		if (!tab.id) continue;
		const outputId = tab.output.result_id;
		if (!outputId) {
			missing.push(`output:${tab.id}`);
			continue;
		}
		outputByTabId.set(tab.id, outputId);
		outputById.set(outputId, tab.id);
	}
	if (missing.length) {
		return null;
	}

	const pipelineTabs = tabs.map((tab) => {
		const outputId = outputByTabId.get(tab.id);
		let datasource: PipelineDatasource;
		try {
			datasource = toPipelineDatasource({
				analysisId,
				datasource: tab.datasource,
				datasourceMap,
				outputById
			});
		} catch {
			return null;
		}
		if (!outputId) return null;
		// Drop response-only UI fields that protobuf pipeline codecs reject.
		const { materialized: _materialized, ...outputFields } = tab.output;
		return {
			id: tab.id,
			name: tab.name,
			datasource,
			output: { ...outputFields, result_id: outputId },
			steps: applySteps(tab.steps ?? []).map((step) => ({
				...step,
				config: normalizeConfig(step.type, step.config)
			}))
		};
	});

	const tabsPayload = pipelineTabs.filter((tab): tab is PipelineTab => tab !== null);
	if (tabsPayload.length !== pipelineTabs.length) return null;
	return { analysis_id: analysisId, tabs: tabsPayload };
}

export function buildDatasourceConfig(args: {
	analysisId: string | null;
	tab: AnalysisTab | null;
	tabs: AnalysisTab[];
	datasources: DataSource[];
}): AnalysisTabDatasourceConfig | null {
	const tab = args.tab;
	if (!tab) return null;
	const base = tab.datasource.config;
	const datasourceId = tab.datasource.id;
	const datasource = args.datasources.find((ds) => ds.id === datasourceId);
	const analysisSourceId = datasource?.created_by_analysis_id ?? null;
	if (!analysisSourceId || !args.analysisId) return base;
	if (analysisSourceId !== args.analysisId) return base;
	const payload = buildAnalysisPipelinePayload(args.analysisId, args.tabs, args.datasources);
	if (!payload) return base;
	return { ...base, analysis_pipeline: payload };
}

export function buildDatasourcePipelinePayload(args: {
	datasource: DataSource;
	datasourceConfig: Record<string, unknown>;
}): AnalysisPipelinePayload {
	const datasource = args.datasource;
	const normalized = normalizeSnapshotConfig(args.datasourceConfig);
	const branch = normalized.branch.trim();
	if (!branch) {
		throw new Error('datasourceConfig.branch is required');
	}
	const normalizedConfig: AnalysisTabDatasourceConfig = { ...normalized, branch };
	if (!datasource.name || !datasource.name.trim()) {
		throw new Error('datasource.name is required');
	}
	const filename = datasource.name.trim().replace(/\s+/g, '_').toLowerCase();
	const previewOutputId = `datasource-preview-${datasource.id}`;
	const tabs: PipelineTab[] = [
		{
			id: `datasource-${datasource.id}`,
			name: datasource.name,
			datasource: {
				id: datasource.id,
				analysis_tab_id: null,
				source_type: datasource.source_type,
				config: normalizedConfig
			},
			output: {
				result_id: previewOutputId,
				format: 'parquet',
				filename: datasource.name,
				build_mode: 'full',
				iceberg: { namespace: 'outputs', table_name: filename, branch }
			},
			steps: []
		}
	];
	return {
		analysis_id: datasource.id,
		tabs
	};
}

export function buildDatasourcePreviewPipelinePayload(args: {
	datasource: DataSource;
	datasourceConfig: Record<string, unknown>;
}): AnalysisPipelinePayload {
	const persistedConfig = isRecord(args.datasource.config) ? args.datasource.config : {};
	return buildDatasourcePipelinePayload({
		datasource: args.datasource,
		datasourceConfig: { ...persistedConfig, ...args.datasourceConfig }
	});
}
