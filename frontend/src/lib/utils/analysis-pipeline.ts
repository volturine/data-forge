import type {
	AnalysisTab,
	AnalysisTabDatasourceConfig,
	AnalysisTabOutput,
	PipelineStep
} from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import { applySteps } from '$lib/utils/pipeline';
import { isRecord } from '$lib/utils/json';

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
	const branch = typeof branchRaw === 'string' && branchRaw.trim() ? branchRaw : 'master';
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

function collectTabSourceIds(tab: AnalysisTab): Set<string> {
	const ids = new Set<string>([tab.datasource.id]);
	for (const step of applySteps(tab.steps ?? [])) {
		const config = step.config ?? {};
		if (!isRecord(config)) continue;
		const cfg = config;
		const rightSource = cfg.right_source ?? cfg.rightDataSource;
		if (typeof rightSource === 'string' && rightSource) ids.add(rightSource);
		const sources = cfg.sources;
		if (typeof sources === 'string' && sources) ids.add(sources);
		if (Array.isArray(sources)) {
			for (const source of sources) {
				if (typeof source === 'string' && source) ids.add(source);
			}
		}
	}
	return ids;
}

function collectSourceIds(tabs: AnalysisTab[]): Set<string> {
	return new Set(tabs.flatMap((tab) => [...collectTabSourceIds(tab)]));
}

function toPipelineDatasource(args: {
	analysisId: string;
	datasource: AnalysisTab['datasource'];
	datasourceMap: Map<string, DataSource>;
	outputById: Map<string, string>;
}): PipelineDatasource | null {
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
		config: { ...toDatasourceConfig(ds.config), ...config }
	};
}

function enrichStepConfig(args: {
	config: Record<string, unknown>;
	datasourceMap: Map<string, DataSource>;
	outputById: Map<string, string>;
}): Record<string, unknown> {
	const next = { ...args.config };
	const rightSource = next.right_source ?? next.rightDataSource;
	if (typeof rightSource === 'string' && rightSource && !args.outputById.has(rightSource)) {
		const ds = args.datasourceMap.get(rightSource);
		if (!ds) return next;
		next.right_source_datasource = {
			id: rightSource,
			analysis_tab_id: null,
			source_type: ds.source_type,
			config: toDatasourceConfig(ds.config)
		} satisfies PipelineDatasource;
	}
	const sources = next.sources;
	const ids = typeof sources === 'string' ? [sources] : Array.isArray(sources) ? sources : [];
	const refs: PipelineDatasource[] = [];
	for (const source of ids) {
		if (typeof source !== 'string' || !source || args.outputById.has(source)) continue;
		const ds = args.datasourceMap.get(source);
		if (!ds) continue;
		refs.push({
			id: source,
			analysis_tab_id: null,
			source_type: ds.source_type,
			config: toDatasourceConfig(ds.config)
		});
	}
	if (refs.length > 0) {
		next.source_datasources = refs;
	}
	return next;
}

export function buildAnalysisPipelinePayload(
	analysisId: string,
	tabs: AnalysisTab[],
	datasources: DataSource[]
): AnalysisPipelinePayload | null {
	if (!analysisId) return null;
	if (!tabs.length) return null;

	const sourceIds = collectSourceIds(tabs);
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
	for (const id of sourceIds) {
		if (outputById.has(id)) continue;
		const ds = datasourceMap.get(id);
		if (!ds) {
			missing.push(id);
		}
	}
	if (missing.length) {
		return null;
	}

	const pipelineTabs = tabs.map((tab) => {
		const outputId = outputByTabId.get(tab.id);
		const datasource = toPipelineDatasource({
			analysisId,
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
			steps: applySteps(tab.steps ?? []).map((step) => {
				const config = step.config;
				if (!isRecord(config)) return step;
				return {
					...step,
					config: enrichStepConfig({ config, datasourceMap, outputById })
				};
			})
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
	datasourceConfig?: Record<string, unknown> | null;
}): AnalysisPipelinePayload {
	const datasource = args.datasource;
	const normalized = normalizeSnapshotConfig(args.datasourceConfig ?? { branch: 'master' });
	const branch = normalized.branch.trim() || 'master';
	const normalizedConfig: AnalysisTabDatasourceConfig = { ...normalized, branch };
	const filename = (datasource.name ?? 'export').replace(/\s+/g, '_').toLowerCase();
	const tabs: PipelineTab[] = [
		{
			id: `datasource-${datasource.id}`,
			name: datasource.name ?? 'Datasource',
			datasource: {
				id: datasource.id,
				analysis_tab_id: null,
				source_type: datasource.source_type,
				config: normalizedConfig
			},
			output: {
				result_id: datasource.id,
				format: 'parquet',
				filename: datasource.name ?? 'export',
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
