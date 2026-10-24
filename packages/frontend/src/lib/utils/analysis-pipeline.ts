import type {
	AnalysisTab,
	AnalysisTabDatasourceConfig,
	AnalysisTabOutput,
	PipelineStep
} from '#lib/types/analysis.js';
import type { DataSource } from '#lib/types/datasource.js';
import { slugify } from '#lib/utils/analysis-tab.js';
import { applySteps } from '#lib/utils/pipeline.js';
import { normalizeConfig } from '#lib/utils/step-config-defaults.js';

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

function branchOf(config: Record<string, unknown>): string {
	const branch = config.branch;
	return typeof branch === 'string' ? branch.trim() : '';
}

function toDatasourceConfig(config: Record<string, unknown>): AnalysisTabDatasourceConfig {
	const branch = branchOf(config);
	if (!branch) {
		throw new Error('datasource config.branch is required');
	}
	return { ...config, branch };
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
	const normalized: AnalysisTabDatasourceConfig = { ...rest };
	if (time_travel_snapshot_id != null) {
		normalized.snapshot_id = time_travel_snapshot_id;
		if (time_travel_snapshot_timestamp_ms != null) {
			normalized.snapshot_timestamp_ms = time_travel_snapshot_timestamp_ms;
		}
	}
	return normalized;
}

function toPipelineDatasource(args: {
	datasource: AnalysisTab['datasource'];
	datasourceMap: Map<string, DataSource>;
	outputById: Map<string, string>;
}): PipelineDatasource | null {
	if (!branchOf(args.datasource.config)) return null;
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
	if (!ds) return null;
	return {
		id: args.datasource.id,
		analysis_tab_id: null,
		source_type: ds.source_type,
		config: normalizeSnapshotConfig({ ...ds.config, ...config })
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
		const datasource = toPipelineDatasource({
			datasource: tab.datasource,
			datasourceMap,
			outputById
		});
		if (!datasource || !outputId) return null;
		return {
			id: tab.id,
			name: tab.name,
			datasource,
			output: { ...tab.output, result_id: outputId },
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

/**
 * Build the pipeline sent for a target preview. The selected tab only needs
 * steps through the target; the other tabs remain available as cross-tab
 * sources and analysis outputs.
 */
export function buildTargetPreviewPipelinePayload(
	pipeline: AnalysisPipelinePayload,
	tabId: string | null,
	targetStepId: string
): AnalysisPipelinePayload | null {
	const requested = tabId ? pipeline.tabs.find((tab) => tab.id === tabId) : undefined;
	const requestedMatches =
		requested &&
		(targetStepId === 'source' || requested.steps.some((step) => step.id === targetStepId));
	const targetTab =
		targetStepId === 'source'
			? undefined
			: pipeline.tabs.find((tab) => tab.steps.some((step) => step.id === targetStepId));
	const selected =
		(requestedMatches ? requested : undefined) ??
		targetTab ??
		pipeline.tabs.find((tab) => tab.steps.length > 0) ??
		pipeline.tabs[0];
	if (!selected) return null;

	const selectedId = selected.id;
	const targetIndex =
		targetStepId === 'source' ? -1 : selected.steps.findIndex((step) => step.id === targetStepId);
	if (targetStepId !== 'source' && targetIndex === -1) return null;

	return {
		...pipeline,
		tabs: pipeline.tabs.map((tab) =>
			tab.id === selectedId
				? { ...tab, steps: targetIndex === -1 ? [] : tab.steps.slice(0, targetIndex + 1) }
				: tab
		)
	};
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
	const normalizedConfig = normalizeSnapshotConfig(args.datasourceConfig);
	const branch = normalizedConfig.branch;
	const filename = slugify(datasource.name, 'datasource.name');
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
	return buildDatasourcePipelinePayload({
		datasource: args.datasource,
		datasourceConfig: { ...args.datasource.config, ...args.datasourceConfig }
	});
}

/** Fire-and-warmup variant: returns null instead of throwing when the persisted
 * config has no branch (and no default was resolved yet). */
export function buildDatasourcePreviewPipelinePayloadSafe(args: {
	datasource: DataSource;
	datasourceConfig: Record<string, unknown>;
}): AnalysisPipelinePayload | null {
	try {
		return buildDatasourcePreviewPipelinePayload(args);
	} catch {
		return null;
	}
}
