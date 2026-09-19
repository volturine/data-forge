import { SvelteSet } from 'svelte/reactivity';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { datasourceStore } from '$lib/stores/datasource.svelte';
import { schemaStore } from '$lib/stores/schema.svelte';
import { getDatasourceSchema } from '$lib/api/datasource';
import type { DataSource } from '$lib/types/datasource';
import { getEngineDefaults, getStepSchema } from '$lib/api/compute';
import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
import { hashPipeline } from '$lib/utils/hash';
import { applySteps } from '$lib/utils/pipeline';
import { createAsyncGate } from '$lib/utils/async-gate';
import { track } from '$lib/utils/audit-log';
import { isUuid } from '$lib/utils/analysis-tab';

type CancellableEffect = (() => void) & { cancel: () => void };

export function setupEngineDefaultsEffect(validAnalysisId: () => string | null): CancellableEffect {
	let controller: AbortController | null = null;
	const run = () => {
		const id = validAnalysisId();
		if (!id || analysisStore.engineDefaults) return;
		controller?.abort();
		controller = new AbortController();
		getEngineDefaults({ signal: controller.signal }).match(
			(defaults) => {
				if (controller?.signal.aborted) return;
				analysisStore.setEngineDefaults(defaults);
			},
			(err) => {
				if (controller?.signal.aborted) return;
				track({
					event: 'engine_error',
					action: 'defaults',
					target: id,
					meta: { message: err.message }
				});
			}
		);
	};
	run.cancel = () => {
		controller?.abort();
		controller = null;
	};
	return run;
}

export function setupInferredSchemaHydrationEffect(
	validAnalysisId: () => string | null
): CancellableEffect {
	const hydratedGates = new SvelteSet<string>();
	const inferredSchemaGate = createAsyncGate();
	const controllers = new SvelteSet<AbortController>();

	const run = () => {
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
		const controller = new AbortController();
		controllers.add(controller);

		const targets = pipeline.filter(
			(step) =>
				(step.type === 'expression' || step.type === 'with_columns') && step.is_applied !== false
		);
		let remaining = targets.length;
		const release = () => {
			remaining -= 1;
			if (remaining <= 0) controllers.delete(controller);
		};
		if (remaining === 0) controllers.delete(controller);
		for (const step of targets) {
			getStepSchema(
				{
					analysis_id: id,
					analysis_pipeline: analysisPayload,
					tab_id: tab.id,
					target_step_id: step.id
				},
				{ signal: controller.signal }
			).match(
				(res) => {
					release();
					if (controller.signal.aborted) {
						hydratedGates.delete(gate);
						return;
					}
					if (!inferredSchemaGate.isCurrent(requestToken)) return;
					if (analysisStore.activeTab?.id !== tab.id) return;
					schemaStore.syncPreviewSchema(step.id, res, pipelineHash);
				},
				(err) => {
					release();
					if (controller.signal.aborted) {
						hydratedGates.delete(gate);
						return;
					}
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
	run.cancel = () => {
		inferredSchemaGate.invalidate();
		for (const controller of controllers) controller.abort();
		controllers.clear();
		hydratedGates.clear();
	};
	return run;
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
	cancel: () => void;
} {
	let isLoadingSchema = $state(false);
	const pendingSourceSchemaKeys = new SvelteSet<string>();
	const controllers = new SvelteSet<AbortController>();

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

		if (analysisTabId) {
			if (!analysisPayload) return;
			const controller = new AbortController();
			controllers.add(controller);
			const releasePendingSchema = () => {
				if (!pendingSourceSchemaKeys.has(requestKey)) return;
				pendingSourceSchemaKeys.delete(requestKey);
				controllers.delete(controller);
				isLoadingSchema = pendingSourceSchemaKeys.size > 0;
			};
			pendingSourceSchemaKeys.add(requestKey);
			isLoadingSchema = true;
			const targetTabId = analysisTabId ?? activeTab?.id ?? null;
			getStepSchema(
				{
					analysis_id: validAnalysisId ?? undefined,
					analysis_pipeline: analysisPayload,
					tab_id: targetTabId,
					target_step_id: 'source'
				},
				{ signal: controller.signal }
			).match(
				(payload) => {
					releasePendingSchema();
					if (controller.signal.aborted) return;
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
				},
				(error) => {
					releasePendingSchema();
					if (controller.signal.aborted) return;
					if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
					track({
						event: 'schema_error',
						action: 'analysis_source_schema',
						target: deps.analysisId() ?? '',
						meta: { message: error.message }
					});
				}
			);
			return;
		}

		const data = deps.datasources();
		if (!data || !datasourceIdValue) return;
		if (!isUuid(datasourceIdValue)) return;
		const ds = data.find((d) => d.id === datasourceIdValue);
		if (ds?.source_type === 'analysis') return;
		const controller = new AbortController();
		controllers.add(controller);
		const releasePendingSchema = () => {
			if (!pendingSourceSchemaKeys.has(requestKey)) return;
			pendingSourceSchemaKeys.delete(requestKey);
			controllers.delete(controller);
			isLoadingSchema = pendingSourceSchemaKeys.size > 0;
		};
		pendingSourceSchemaKeys.add(requestKey);
		isLoadingSchema = true;
		getDatasourceSchema(datasourceIdValue, { signal: controller.signal }).match(
			(schema) => {
				releasePendingSchema();
				if (controller.signal.aborted) return;
				if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
				analysisStore.setSourceSchema(schemaId, schema);
			},
			(err) => {
				releasePendingSchema();
				if (controller.signal.aborted) return;
				if (deps.schemaKey() !== schemaId || analysisStore.activeTab?.id !== activeTabId) return;
				track({
					event: 'schema_error',
					action: 'load',
					target: datasourceIdValue,
					meta: { message: err.message }
				});
			}
		);
	}

	return {
		load,
		isLoading: () => isLoadingSchema,
		cancel: () => {
			for (const controller of controllers) controller.abort();
			controllers.clear();
			pendingSourceSchemaKeys.clear();
			isLoadingSchema = false;
		}
	};
}
