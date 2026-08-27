import { SvelteSet } from 'svelte/reactivity';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { datasourceStore } from '$lib/stores/datasource.svelte';
import { schemaStore } from '$lib/stores/schema.svelte';
import { getDatasourceSchema } from '$lib/api/datasource';
import type { DataSource } from '$lib/types/datasource';
import { getEngineDefaults, getStepSchema, spawnAnalysisEngine } from '$lib/api/compute';
import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
import { hashPipeline } from '$lib/utils/hash';
import { applySteps } from '$lib/utils/pipeline';
import { createAsyncGate } from '$lib/utils/async-gate';
import { track } from '$lib/utils/audit-log';
import { isUuid } from '$lib/utils/analysis-tab';

export function setupEngineDefaultsEffect(validAnalysisId: () => string | null): () => void {
	return () => {
		const id = validAnalysisId();
		if (!id || analysisStore.engineDefaults) return;
		getEngineDefaults().match(
			(defaults) => {
				analysisStore.setEngineDefaults(defaults);
			},
			(err) => {
				track({
					event: 'engine_error',
					action: 'defaults',
					target: id,
					meta: { message: err.message }
				});
			}
		);
	};
}

export function setupEngineWarmupEffect(validAnalysisId: () => string | null): {
	start: () => void;
	stop: () => void;
} {
	let warmedEngineIdentityCache: string | null = null;
	let alive = false;
	let timer = 0;

	function stop(): void {
		alive = false;
		if (timer) window.clearTimeout(timer);
		timer = 0;
	}

	function start(): void {
		stop();
		const id = validAnalysisId();
		if (!id) {
			analysisStore.previews.paused = false;
			warmedEngineIdentityCache = null;
			return;
		}
		const nextKey = `${id}:${JSON.stringify(analysisStore.resourceConfig ?? {})}`;
		if (warmedEngineIdentityCache === nextKey) {
			analysisStore.previews.paused = false;
			return;
		}
		warmedEngineIdentityCache = nextKey;
		alive = true;
		timer = window.setTimeout(() => {
			if (!alive) return;
			spawnAnalysisEngine(id, analysisStore.resourceConfig ?? undefined).match(
				() => {
					if (!alive) return;
					analysisStore.previews.paused = false;
				},
				(err) => {
					if (!alive) return;
					track({
						event: 'engine_error',
						action: 'prewarm',
						target: id,
						meta: { message: err.message }
					});
					analysisStore.previews.paused = false;
				}
			);
		}, 300);
	}

	return { start, stop };
}

export function setupInferredSchemaHydrationEffect(
	validAnalysisId: () => string | null
): () => void {
	const hydratedGates = new SvelteSet<string>();
	const inferredSchemaGate = createAsyncGate();

	return () => {
		const id = validAnalysisId();
		if (!id) return;
		const tab = analysisStore.activeTab;
		if (!tab) return;
		const pipeline = analysisStore.pipeline;
		if (!pipeline.length) return;
		const analysisPayload = buildAnalysisPipelinePayload(
			id,
			analysisStore.tabs,
			datasourceStore.datasources
		);
		if (!analysisPayload) return;
		const pipelineHash = hashPipeline(applySteps(pipeline));
		const gate = `${id}:${tab.id}:${pipelineHash}`;
		if (hydratedGates.has(gate)) return;
		hydratedGates.add(gate);
		const requestToken = inferredSchemaGate.issue();

		const targets = pipeline.filter(
			(step) =>
				(step.type === 'expression' || step.type === 'with_columns') && step.is_applied !== false
		);
		for (const step of targets) {
			getStepSchema({
				analysis_id: id,
				analysis_pipeline: analysisPayload,
				tab_id: tab.id,
				target_step_id: step.id
			}).match(
				(res) => {
					if (!inferredSchemaGate.isCurrent(requestToken)) return;
					if (analysisStore.activeTab?.id !== tab.id) return;
					schemaStore.syncPreviewSchema(step.id, res, pipelineHash);
				},
				(err) => {
					if (!inferredSchemaGate.isCurrent(requestToken)) return;
					if (analysisStore.activeTab?.id !== tab.id) return;
					track({
						event: 'schema_error',
						action: 'hydrate',
						target: step.id,
						meta: { message: err.message }
					});
				}
			);
		}
	};
}

export type SourceSchemaLoaderDeps = {
	validAnalysisId: () => string | null;
	analysisId: () => string | null;
	datasourceId: () => string | null;
	schemaKey: () => string | undefined;
	datasources: () => DataSource[] | undefined;
};

export function setupSourceSchemaLoadingEffect(deps: SourceSchemaLoaderDeps): {
	load: () => void;
	isLoading: () => boolean;
} {
	let isLoadingSchema = $state(false);
	const pendingSourceSchemaKeys = new SvelteSet<string>();

	function load(): void {
		const datasourceIdValue = deps.datasourceId();
		const schemaId = deps.schemaKey();
		if (!schemaId) return;
		const activeTabId = analysisStore.activeTab?.id ?? null;
		const requestKey = `${schemaId}:${activeTabId ?? ''}`;

		const existingSchema = analysisStore.sourceSchemas.get(schemaId);
		if (existingSchema || pendingSourceSchemaKeys.has(requestKey)) return;

		const activeTab = analysisStore.activeTab;
		const analysisTabId = activeTab?.datasource?.analysis_tab_id ?? null;
		const validAnalysisId = deps.validAnalysisId();
		const analysisPayload = validAnalysisId
			? buildAnalysisPipelinePayload(
					validAnalysisId,
					analysisStore.tabs,
					datasourceStore.datasources
				)
			: null;
		const releasePendingSchema = () => {
			if (!pendingSourceSchemaKeys.has(requestKey)) return;
			pendingSourceSchemaKeys.delete(requestKey);
		};

		if (analysisTabId) {
			if (!analysisPayload) return;
			pendingSourceSchemaKeys.add(requestKey);
			isLoadingSchema = true;
			const targetTabId = analysisTabId ?? activeTab?.id ?? null;
			getStepSchema({
				analysis_id: validAnalysisId ?? undefined,
				analysis_pipeline: analysisPayload,
				tab_id: targetTabId,
				target_step_id: 'source'
			}).match(
				(payload) => {
					releasePendingSchema();
					if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
					const columns = payload.columns.map((name) => ({
						name,
						dtype: payload.column_types[name] ?? 'unknown',
						nullable: true
					}));
					analysisStore.setSourceSchema(schemaId, {
						columns,
						row_count: null
					});
					isLoadingSchema = false;
				},
				(error) => {
					releasePendingSchema();
					if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
					track({
						event: 'schema_error',
						action: 'analysis_source_schema',
						target: deps.analysisId() ?? '',
						meta: { message: error.message }
					});
					isLoadingSchema = false;
				}
			);
			return;
		}

		const data = deps.datasources();
		if (!data || !datasourceIdValue) return;
		if (!isUuid(datasourceIdValue)) return;
		const ds = data.find((d) => d.id === datasourceIdValue);
		if (ds?.source_type === 'analysis') return;
		pendingSourceSchemaKeys.add(requestKey);
		isLoadingSchema = true;
		getDatasourceSchema(datasourceIdValue).match(
			(schema) => {
				releasePendingSchema();
				if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
				analysisStore.setSourceSchema(schemaId, schema);
				isLoadingSchema = false;
			},
			(err) => {
				releasePendingSchema();
				if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
				track({
					event: 'schema_error',
					action: 'load',
					target: datasourceIdValue,
					meta: { message: err.message }
				});
				isLoadingSchema = false;
			}
		);
	}

	return {
		load,
		isLoading: () => isLoadingSchema
	};
}
