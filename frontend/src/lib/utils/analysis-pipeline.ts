import type { AnalysisTab, PipelineStep } from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import { applySteps } from '$lib/utils/pipeline';

type PipelineTab = {
	id: string;
	name: string;
	datasource: {
		id: string;
		analysis_tab_id: string | null;
		config: { branch: string } & Record<string, unknown>;
	};
	output: {
		result_id: string;
		format: string;
		filename: string;
		build_mode?: string;
		iceberg?: Record<string, unknown>;
	} & Record<string, unknown>;
	steps: PipelineStep[];
};

export type AnalysisPipelinePayload = {
	analysis_id: string;
	tabs: PipelineTab[];
	sources: Record<string, Record<string, unknown>>;
};

/**
 * Normalize time-travel fields into compute-ready snapshot fields.
 * Strips `time_travel_snapshot_id`, `time_travel_snapshot_timestamp_ms`,
 * and `time_travel_ui` from the config, mapping the first two into
 * `snapshot_id` / `snapshot_timestamp_ms` for the engine.
 */
export function normalizeSnapshotConfig(config: Record<string, unknown>): Record<string, unknown> {
	const {
		time_travel_snapshot_id,
		time_travel_snapshot_timestamp_ms,
		time_travel_ui: _ui,
		...rest
	} = config;
	if (time_travel_snapshot_id != null) {
		rest.snapshot_id = time_travel_snapshot_id;
		if (time_travel_snapshot_timestamp_ms != null) {
			rest.snapshot_timestamp_ms = time_travel_snapshot_timestamp_ms;
		}
	}
	return rest;
}

function collectTabSourceIds(tab: AnalysisTab): Set<string> {
	const ids = new Set<string>([tab.datasource.id]);
	for (const step of applySteps(tab.steps ?? [])) {
		const config = step.config ?? {};
		if (typeof config !== 'object' || Array.isArray(config)) continue;
		const cfg = config as Record<string, unknown>;
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

export function buildAnalysisPipelinePayload(
	analysisId: string,
	tabs: AnalysisTab[],
	datasources: DataSource[]
): AnalysisPipelinePayload | null {
	if (!analysisId) return null;
	if (!tabs.length) return null;

	const sourceIds = collectSourceIds(tabs);
	const datasourceMap = new Map(datasources.map((ds) => [ds.id, ds]));
	const sources: Record<string, Record<string, unknown>> = {};
	const missing: string[] = [];
	const outputByTabId = new Map<string, string>();
	for (const tab of tabs) {
		if (!tab.id) continue;
		const outputId = tab.output.result_id;
		if (!outputId) {
			missing.push(`output:${tab.id}`);
			continue;
		}
		outputByTabId.set(tab.id, outputId);
		sources[outputId] = {
			source_type: 'analysis',
			analysis_id: analysisId,
			analysis_tab_id: tab.id
		};
	}
	for (const id of sourceIds) {
		if (sources[id]) continue;
		const ds = datasourceMap.get(id);
		if (!ds) {
			missing.push(id);
			continue;
		}
		sources[id] = { source_type: ds.source_type, ...ds.config };
	}
	if (missing.length) {
		return null;
	}

	const pipelineTabs = tabs.map((tab) => {
		const outputId = outputByTabId.get(tab.id);
		const config = normalizeSnapshotConfig(tab.datasource.config as Record<string, unknown>);
		const datasourceId = tab.datasource.id;
		const analysisTabId = tab.datasource.analysis_tab_id;
		if (!datasourceId || !outputId) return null;
		return {
			id: tab.id,
			name: tab.name,
			datasource: {
				id: datasourceId,
				analysis_tab_id: analysisTabId,
				config: config as { branch: string } & Record<string, unknown>
			},
			output: { ...tab.output, result_id: outputId },
			steps: applySteps(tab.steps ?? [])
		};
	});

	const tabsPayload = pipelineTabs.filter((tab): tab is PipelineTab => tab !== null);
	if (tabsPayload.length !== pipelineTabs.length) return null;
	return { analysis_id: analysisId, tabs: tabsPayload, sources };
}

export function buildDatasourceConfig(args: {
	analysisId: string | null;
	tab: AnalysisTab | null;
	tabs: AnalysisTab[];
	datasources: DataSource[];
}): Record<string, unknown> | null {
	const tab = args.tab;
	if (!tab) return null;
	const base = tab.datasource.config as Record<string, unknown>;
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
	const normalized = normalizeSnapshotConfig(args.datasourceConfig ?? {});
	const branch = String(
		(normalized as { branch?: string } | null | undefined)?.branch ?? 'master'
	).trim();
	const filename = (datasource.name ?? 'export').replace(/\s+/g, '_').toLowerCase();
	const tabs: PipelineTab[] = [
		{
			id: `datasource-${datasource.id}`,
			name: datasource.name ?? 'Datasource',
			datasource: {
				id: datasource.id,
				analysis_tab_id: null,
				config: { branch, ...normalized }
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
		tabs,
		sources: {
			[datasource.id]: { source_type: datasource.source_type, ...datasource.config }
		}
	};
}
