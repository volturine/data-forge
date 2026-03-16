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
		const ds = datasourceMap.get(id);
		if (!ds) {
			if (!sources[id]) missing.push(id);
			continue;
		}
		// Real datasource configs take priority over output analysis refs
		sources[id] = { source_type: ds.source_type, ...ds.config };
	}
	if (missing.length) {
		return null;
	}

	const pipelineTabs = tabs.map((tab) => {
		const outputId = outputByTabId.get(tab.id);
		const config = tab.datasource.config;
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

export function buildTabPipelinePayload(args: {
	analysisId: string;
	tab: AnalysisTab | null;
	tabs: AnalysisTab[];
	datasources: DataSource[];
}): AnalysisPipelinePayload | null {
	const tab = args.tab;
	if (!tab) return null;

	const outputMap = new Map<string, string>();
	const outputById = new Map<string, string>();
	for (const item of args.tabs) {
		if (!item.id) continue;
		const outputId = item.output.result_id;
		if (!outputId) continue;
		outputMap.set(item.id, outputId);
		outputById.set(outputId, item.id);
	}

	const config = tab.datasource.config;
	const datasourceId = tab.datasource.id;
	const analysisTabId = tab.datasource.analysis_tab_id;
	if (!datasourceId) return null;

	const steps = applySteps(tab.steps ?? []);
	const datasourceMap = new Map(args.datasources.map((ds) => [ds.id, ds]));
	const sources: Record<string, Record<string, unknown>> = {};

	const addAnalysisSource = (tabId: string) => {
		const outputId = outputMap.get(tabId);
		if (!outputId) return;
		sources[outputId] = {
			source_type: 'analysis',
			analysis_id: args.analysisId,
			analysis_tab_id: tabId
		};
	};

	const sourceIds = collectTabSourceIds(tab);
	for (const sourceId of sourceIds) {
		const tabId = outputById.get(sourceId);
		if (tabId) {
			addAnalysisSource(tabId);
			continue;
		}
		const ds = datasourceMap.get(sourceId);
		if (!ds) continue;
		sources[sourceId] = { source_type: ds.source_type, ...ds.config };
	}

	if (analysisTabId) {
		addAnalysisSource(String(analysisTabId));
	}

	return {
		analysis_id: args.analysisId,
		tabs: [
			{
				id: tab.id,
				name: tab.name,
				datasource: {
					id: datasourceId,
					analysis_tab_id: analysisTabId,
					config: config as { branch: string } & Record<string, unknown>
				},
				output: { ...tab.output },
				steps
			}
		],
		sources
	};
}

export function buildDatasourcePipelinePayload(args: {
	datasource: DataSource;
	datasourceConfig?: Record<string, unknown> | null;
}): AnalysisPipelinePayload {
	const datasource = args.datasource;
	const branch = String(
		(args.datasourceConfig as { branch?: string } | null | undefined)?.branch ?? 'master'
	).trim();
	const filename = (datasource.name ?? 'export').replace(/\s+/g, '_').toLowerCase();
	const tabs: PipelineTab[] = [
		{
			id: `datasource-${datasource.id}`,
			name: datasource.name ?? 'Datasource',
			datasource: {
				id: datasource.id,
				analysis_tab_id: null,
				config: { branch, ...(args.datasourceConfig ?? {}) }
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
