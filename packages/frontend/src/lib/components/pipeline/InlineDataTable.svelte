<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { onDestroy } from 'svelte';
	import { previewStepData, throwIfAborted, type StepPreviewResponse } from '#lib/api/compute.js';
	import {
		createPreviewRequestCancellation,
		PREVIEW_QUERY_GC_TIME,
		stepPreviewQueryKey
	} from '#lib/utils/preview-query.js';
	import { applySteps, stepsThroughTarget } from '#lib/utils/pipeline.js';
	import { toComputeError } from '#lib/utils/compute-error.js';
	import { hashPipeline } from '#lib/utils/hash.js';
	import { analysisStore } from '#lib/stores/analysis.svelte.js';
	import { datasourceStore } from '#lib/stores/datasource.svelte.js';
	import { schemaStore } from '#lib/stores/schema.svelte.js';
	import { isNamespaceReady, requireNamespace } from '#lib/stores/namespace.svelte.js';
	import {
		buildAnalysisPipelinePayload,
		buildTargetPreviewPipelinePayload
	} from '#lib/utils/analysis-pipeline.js';
	import DataTable from '#lib/components/common/DataTable.svelte';
	import { css } from '#lib/styles/panda.js';

	interface Props {
		analysisId: string;
		datasourceId: string;
		pipeline: Array<{
			id: string;
			type: string;
			config: Record<string, unknown>;
			depends_on?: string[];
		}>;
		stepId: string;
		rowLimit?: number;
	}

	let { analysisId, datasourceId, pipeline, stepId, rowLimit = 100 }: Props = $props();
	let currentPage = $state(1);
	let columnSearch = $state('');
	const previewRequestCancellation = createPreviewRequestCancellation();

	onDestroy(() => previewRequestCancellation.dispose());

	const activePipeline = $derived(applySteps(pipeline));
	const isActiveStep = $derived(activePipeline.some((step) => step.id === stepId));
	const targetSteps = $derived(stepsThroughTarget(activePipeline, stepId));
	const pipelineKey = $derived(hashPipeline(targetSteps));
	const namespace = $derived(isNamespaceReady() ? requireNamespace() : null);
	const targetAnalysisPipeline = $derived.by(() => {
		if (!analysisId) return null;
		const pipeline = buildAnalysisPipelinePayload(
			analysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
		if (!pipeline) return null;
		return buildTargetPreviewPipelinePayload(pipeline, analysisStore.activeTab?.id ?? null, stepId);
	});
	const previewRequestState = $derived.by(() => {
		if (!targetAnalysisPipeline) return null;
		return {
			request: {
				analysis_id: analysisId,
				analysis_pipeline: targetAnalysisPipeline,
				tab_id: analysisStore.activeTab?.id ?? null,
				target_step_id: stepId,
				row_limit: rowLimit,
				page: currentPage,
				resource_config: analysisStore.resourceConfig
			},
			pipelineKey
		};
	});

	const query = createQuery(() => ({
		// Cache and execute from the exact target command in the key. Later steps
		// in this tab cannot change this preview; other tabs remain for sources.
		queryKey: [
			...stepPreviewQueryKey(namespace, analysisId, stepId),
			datasourceId,
			previewRequestState
		] as const,
		queryFn: async ({ queryKey }): Promise<StepPreviewResponse> => {
			const state = queryKey[5];
			if (!state) throw new Error('Preview command is not ready');
			const { request } = state;
			const signal = previewRequestCancellation.signalFor(request);
			const result = await previewStepData(request, { signal });
			throwIfAborted(signal);
			if (result.isErr()) {
				throw toComputeError(result.error);
			}
			schemaStore.syncPreviewSchema(stepId, result.value, state.pipelineKey);
			return result.value;
		},
		staleTime: Infinity,
		gcTime: PREVIEW_QUERY_GC_TIME,
		// Cache-option Apply invalidates this target's variants; fresh navigation entries stay cached.
		refetchOnMount: true,
		retry: false,
		enabled: isActiveStep && !!namespace && !!previewRequestState && !analysisStore.previews.paused
	}));

	const data = $derived(isActiveStep ? query.data : null);
	const isLoading = $derived(isActiveStep ? query.isFetching : false);
	const error = $derived(isActiveStep ? query.error : null);
	const errorMessage = $derived(error instanceof Error ? error.message : '');
	const previewState = $derived.by(() => {
		if (!isActiveStep) return 'inactive';
		if (!targetAnalysisPipeline) return 'waiting-for-payload';
		if (error) return 'error';
		if (analysisStore.previews.paused) return 'paused';
		if (isLoading) return 'loading';
		if (data) return 'ready';
		return 'idle';
	});
	const pageSize = $derived(data?.data?.length ?? 0);
	const canPrev = $derived(currentPage > 1);
	const canNext = $derived(pageSize === rowLimit);

	function runPreview() {
		if (!isActiveStep || analysisStore.previews.paused) return;
		query.refetch();
	}

	function nextPage() {
		if (!canNext) return;
		currentPage++;
	}

	function prevPage() {
		if (!canPrev) return;
		currentPage--;
	}
</script>

<div
	class={css({ contain: 'content', width: 'full', height: 'panel', overflow: 'hidden' })}
	data-testid="inline-data-table"
	data-preview-ready={data && !isLoading && !error ? 'true' : undefined}
	data-preview-state={previewState}
	data-preview-query-status={query.status}
	data-preview-fetch-status={query.fetchStatus}
	data-preview-has-data={query.data ? 'true' : 'false'}
	data-preview-columns={data?.columns.length ?? 0}
	data-preview-error={errorMessage || undefined}
>
	<DataTable
		columns={data?.columns ?? []}
		data={data?.data ?? []}
		columnTypes={data?.column_types ?? {}}
		loading={isLoading}
		analysis={true}
		onPreview={runPreview}
		{error}
		fillContainer
		bind:columnSearch
		showHeader
		showPagination
		pagination={{
			page: currentPage,
			canPrev,
			canNext,
			onPrev: prevPage,
			onNext: nextPage
		}}
		showTypeBadges
		showFooter={false}
	/>
</div>
