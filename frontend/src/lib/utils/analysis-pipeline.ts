import type { AnalysisTab, PipelineStep } from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import { ensureTabDefaults } from '$lib/utils/analysis-tab';
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
		output_datasource_id: string;
		datasource_type: string;
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

function getTabSteps(tab: AnalysisTab): PipelineStep[] {
	return applySteps(tab.steps ?? []);
}

function collectSourceIds(tabs: AnalysisTab[]): Set<string> {
	const ids = new Set<string>();
	for (const tab of tabs) {
		const datasourceId = tab.datasource.id;
		ids.add(datasourceId);
		const steps = getTabSteps(tab);
		for (const step of steps) {
			const config = step.config ?? {};
			if (typeof config !== 'object' || Array.isArray(config)) {
				continue;
			}
			const rightSource =
				(config as Record<string, unknown>).right_source ??
				(config as Record<string, unknown>).rightDataSource;
			if (typeof rightSource === 'string' && rightSource) {
				ids.add(rightSource);
			}
			const sources = (config as Record<string, unknown>).sources;
			if (typeof sources === 'string' && sources) {
				ids.add(sources);
			}
			if (Array.isArray(sources)) {
				for (const source of sources) {
					if (typeof source === 'string' && source) {
						ids.add(source);
					}
				}
			}
		}
	}
	return ids;
}

function collectTabSourceIds(tab: AnalysisTab): Set<string> {
	const ids = new Set<string>();
	const datasourceId = tab.datasource.id;
	ids.add(datasourceId);
	const steps = applySteps(tab.steps ?? []);
	for (const step of steps) {
		const config = step.config ?? {};
		if (typeof config !== 'object' || Array.isArray(config)) {
			continue;
		}
		const rightSource =
			(config as Record<string, unknown>).right_source ??
			(config as Record<string, unknown>).rightDataSource;
		if (typeof rightSource === 'string' && rightSource) {
			ids.add(rightSource);
		}
		const sources = (config as Record<string, unknown>).sources;
		if (typeof sources === 'string' && sources) {
			ids.add(sources);
		}
		if (Array.isArray(sources)) {
			for (const source of sources) {
				if (typeof source === 'string' && source) {
					ids.add(source);
				}
			}
		}
	}
	return ids;
}

export function buildAnalysisPipelinePayload(
	analysisId: string,
	tabs: AnalysisTab[],
	datasources: DataSource[]
): AnalysisPipelinePayload | null {
	if (!analysisId) return null;
	if (!tabs.length) return null;

	const normalizedTabs = tabs.map((tab, index) => ensureTabDefaults(tab, index));
	const sourceIds = collectSourceIds(normalizedTabs);
	const datasourceMap = new Map(datasources.map((ds) => [ds.id, ds]));
	const sources: Record<string, Record<string, unknown>> = {};
	const missing: string[] = [];
	const outputByTabId = new Map<string, string>();
	for (const tab of normalizedTabs) {
		if (!tab.id) continue;
		const outputId = tab.output.output_datasource_id;
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

	const pipelineTabs = normalizedTabs.map((tab) => {
		const outputId = outputByTabId.get(tab.id);
		const config = tab.datasource.config;
		const datasourceId = tab.datasource.id;
		const analysisTabId = tab.datasource.analysis_tab_id;
		if (!datasourceId) {
			missing.push(`datasource:${tab.id}`);
		}
		if (!outputId) {
			missing.push(`output:${tab.id}`);
		}
		if (!datasourceId || !outputId) return null;
		return {
			id: tab.id,
			name: tab.name,
			datasource: {
				id: datasourceId,
				analysis_tab_id: analysisTabId,
				config: config as { branch: string } & Record<string, unknown>
			},
			output: { ...tab.output, output_datasource_id: outputId },
			steps: getTabSteps(tab)
		};
	});

	if (pipelineTabs.some((tab) => tab === null)) {
		return null;
	}

	const tabsPayload = pipelineTabs.filter((tab): tab is PipelineTab => tab !== null);
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
	const tabIndex = args.tabs.findIndex((item) => item.id === tab.id);
	const normalizedTab = ensureTabDefaults(tab, tabIndex >= 0 ? tabIndex : 0);
	for (const item of args.tabs) {
		if (!item.id) continue;
		const outputId = item.output.output_datasource_id;
		if (!outputId) continue;
		outputMap.set(item.id, outputId);
		outputById.set(outputId, item.id);
	}

	const config = normalizedTab.datasource.config;
	const datasourceId = normalizedTab.datasource.id;
	const analysisTabId = normalizedTab.datasource.analysis_tab_id;
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

	const sourceIds = collectTabSourceIds(normalizedTab);
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
				id: normalizedTab.id,
				name: normalizedTab.name,
				datasource: {
					id: datasourceId,
					analysis_tab_id: analysisTabId,
					config: config as { branch: string } & Record<string, unknown>
				},
				output: {
					...normalizedTab.output,
					output_datasource_id: normalizedTab.output.output_datasource_id
				},
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
	const tabs: PipelineTab[] = [
		{
			id: `datasource-${datasource.id}`,
			name: datasource.name ?? 'Datasource',
			datasource: {
				id: datasource.id,
				analysis_tab_id: null,
				config: {
					branch: String(
						(args.datasourceConfig as { branch?: string } | null | undefined)?.branch ?? ''
					).trim(),
					...(args.datasourceConfig ?? {})
				}
			},
			output: {
				output_datasource_id: datasource.id,
				datasource_type: 'iceberg',
				format: 'parquet',
				filename: datasource.name ?? 'export',
				build_mode: 'full',
				iceberg: {
					namespace: 'outputs',
					table_name: (datasource.name ?? 'export').replace(/\s+/g, '_').toLowerCase(),
					branch: String(
						(args.datasourceConfig as { branch?: string } | null | undefined)?.branch ?? 'master'
					).trim()
				}
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
