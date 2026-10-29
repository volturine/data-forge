import { SvelteSet } from 'svelte/reactivity';
import { analysisStore } from '#lib/stores/analysis.svelte.js';
import { datasourceStore } from '#lib/stores/datasource.svelte.js';
import { schemaStore } from '#lib/stores/schema.svelte.js';
import { getDatasourceSchema } from '#lib/api/datasource.js';
import type { DataSource } from '#lib/types/datasource.js';
import { getStepSchema } from '#lib/api/compute.js';
import {
	buildAnalysisPipelinePayload,
	buildTargetPreviewPipelinePayload
} from '#lib/utils/analysis-pipeline.js';
import { hashPipeline } from '#lib/utils/hash.js';
import { applySteps, stepsThroughTarget } from '#lib/utils/pipeline.js';
import { createAsyncGate } from '#lib/utils/async-gate.js';
import { track } from '#lib/utils/audit-log.js';
import { isUuid } from '#lib/utils/analysis-tab.js';

type CancellableEffect = (() => void) & { cancel: () => void };

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
		const appliedPipeline = applySteps(pipeline);
		const pipelineHash = hashPipeline(appliedPipeline);
		const gate = `${id}:${tab.id}:${pipelineHash}`;
		if (hydratedGates.has(gate)) return;
		hydratedGates.add(gate);
		const requestToken = inferredSchemaGate.issue();
		const controller = new AbortController();
		controllers.add(controller);

		const targets = pipeline
			.filter(
				(step) =>
					(step.type === 'expression' || step.type === 'with_columns') && step.is_applied !== false
			)
			.flatMap((step) => {
				const targetPipeline = buildTargetPreviewPipelinePayload(analysisPayload, tab.id, step.id);
				if (!targetPipeline) return [];
				return [
					{
						step,
						pipeline: targetPipeline,
						hash: hashPipeline(stepsThroughTarget(appliedPipeline, step.id))
					}
				];
			});
		let remaining = targets.length;
		const release = () => {
			remaining -= 1;
			if (remaining <= 0) controllers.delete(controller);
		};
		if (remaining === 0) controllers.delete(controller);
		for (const target of targets) {
			const { step } = target;
			getStepSchema(
				{
					analysis_id: id,
					analysis_pipeline: target.pipeline,
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
					schemaStore.syncPreviewSchema(step.id, res, target.hash);
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

	function startSourceRequest(schemaId: string): {
		controller: AbortController;
		release: () => void;
	} {
		const controller = new AbortController();
		controllers.add(controller);
		const release = () => {
			if (!pendingSourceSchemaKeys.has(schemaId)) return;
			pendingSourceSchemaKeys.delete(schemaId);
			controllers.delete(controller);
			isLoadingSchema = pendingSourceSchemaKeys.size > 0;
		};
		pendingSourceSchemaKeys.add(schemaId);
		isLoadingSchema = true;
		return { controller, release };
	}

	function load(): void {
		const datasourceIdValue = deps.datasourceId();
		const schemaId = deps.schemaKey();
		if (!schemaId) return;

		const existingSchema = analysisStore.sourceSchemas.get(schemaId);
		if (existingSchema || pendingSourceSchemaKeys.has(schemaId)) return;

		const activeTab = analysisStore.activeTab;
		const analysisTabId = activeTab?.datasource?.analysis_tab_id ?? null;

		if (analysisTabId) {
			const validAnalysisId = deps.validAnalysisId();
			const analysisPayload = validAnalysisId
				? buildAnalysisPipelinePayload(
						validAnalysisId,
						analysisStore.tabs,
						datasourceStore.datasources
					)
				: null;
			if (!analysisPayload) return;
			const request = startSourceRequest(schemaId);
			getStepSchema(
				{
					analysis_id: validAnalysisId ?? undefined,
					analysis_pipeline: analysisPayload,
					tab_id: analysisTabId,
					target_step_id: 'source'
				},
				{ signal: request.controller.signal }
			).match(
				(payload) => {
					request.release();
					if (request.controller.signal.aborted) return;
					if (deps.schemaKey() !== schemaId) return;
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
					request.release();
					if (request.controller.signal.aborted) return;
					if (deps.schemaKey() !== schemaId) return;
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
		const request = startSourceRequest(schemaId);
		getDatasourceSchema(datasourceIdValue, { signal: request.controller.signal }).match(
			(schema) => {
				request.release();
				if (request.controller.signal.aborted) return;
				if (deps.schemaKey() !== schemaId) return;
				analysisStore.setSourceSchema(schemaId, schema);
			},
			(err) => {
				request.release();
				if (request.controller.signal.aborted) return;
				if (deps.schemaKey() !== schemaId) return;
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
