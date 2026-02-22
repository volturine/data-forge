import type { AnalysisTab, PipelineStep } from '$lib/types/analysis';
import type { DataSource } from '$lib/types/datasource';
import { applySteps } from '$lib/utils/pipeline';

type PipelineTab = {
	id: string;
	name: string;
	datasource_id: string | null;
	output_datasource_id: string | null;
	datasource_config: Record<string, unknown> | null;
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
		if (tab.datasource_id) {
			ids.add(tab.datasource_id);
		}
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
		const outputId = tab.output_datasource_id ?? null;
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
		const outputId = outputByTabId.get(tab.id) ?? null;
		const config = (tab.datasource_config as Record<string, unknown> | null) ?? null;
		let datasourceId = tab.datasource_id ?? null;
		if (config?.analysis_id === analysisId && config?.analysis_tab_id) {
			datasourceId = outputByTabId.get(String(config.analysis_tab_id)) ?? datasourceId;
		}
		return {
			id: tab.id,
			name: tab.name,
			datasource_id: datasourceId,
			output_datasource_id: outputId,
			datasource_config: config,
			steps: getTabSteps(tab)
		};
	});

	return { analysis_id: analysisId, tabs: pipelineTabs, sources };
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
			datasource_id: datasource.id,
			output_datasource_id: null,
			datasource_config: args.datasourceConfig ?? null,
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
	const base = (tab.datasource_config ?? {}) as Record<string, unknown>;
	const datasourceId = tab.datasource_id ?? null;
	if (!datasourceId) return base;
	const datasource = args.datasources.find((ds) => ds.id === datasourceId) ?? null;
	const analysisSourceId =
		(base.analysis_id as string | null | undefined) ??
		((datasource?.config as Record<string, unknown> | null)?.analysis_id as
			| string
			| null
			| undefined) ??
		null;
	if (!analysisSourceId || !args.analysisId) return base;
	if (analysisSourceId !== args.analysisId) return base;
	const payload = buildAnalysisPipelinePayload(args.analysisId, args.tabs, args.datasources);
	if (!payload) return base;
	return { ...base, analysis_pipeline: payload };
}
