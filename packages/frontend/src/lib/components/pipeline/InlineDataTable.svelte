<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import type { StepPreviewResponse } from '$lib/api/compute';
	import { applySteps } from '$lib/utils/pipeline';
	import { fetchPreviewQueryData } from '$lib/utils/preview-query';
	import { hashPipeline } from '$lib/utils/hash';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { isNamespaceReady, requireNamespace } from '$lib/stores/namespace.svelte';
	import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
	import DataTable from '$lib/components/common/DataTable.svelte';
	import { css } from '$lib/styles/panda';

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
	const activePipeline = $derived(applySteps(pipeline));
	const isActiveStep = $derived(activePipeline.some((step) => step.id === stepId));
	const pipelineKey = $derived(hashPipeline(activePipeline));
	const namespace = $derived(isNamespaceReady() ? requireNamespace() : null);
	const analysisPipeline = $derived.by(() => {
		if (!analysisId) return null;
		return buildAnalysisPipelinePayload(
			analysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
	});
	const previewRequestState = $derived.by(() => {
		if (!analysisPipeline) return null;
		return {
			request: {
				analysis_id: analysisId,
				analysis_pipeline: analysisPipeline,
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
		// Cache and execute from the exact command in the key. A pipeline-only
		// hash omits tab, resource settings, and other result-changing inputs.
		queryKey: ['step-preview', namespace, analysisId, datasourceId, previewRequestState] as const,
		queryFn: async ({ queryKey, signal }): Promise<StepPreviewResponse> => {
			const state = queryKey[4];
			if (!state) throw new Error('Preview command is not ready');
			const data = await fetchPreviewQueryData(state.request, signal);
			schemaStore.syncPreviewSchema(stepId, data, state.pipelineKey);
			return data;
		},
		staleTime: Infinity,
		gcTime: Infinity,
		refetchOnMount: false,
		retry: false,
		enabled: isActiveStep && !!namespace && !!previewRequestState && !analysisStore.previews.paused
	}));

	const data = $derived(isActiveStep ? query.data : null);
	const isLoading = $derived(isActiveStep ? query.isFetching : false);
	const error = $derived(isActiveStep ? query.error : null);
	const errorMessage = $derived(error instanceof Error ? error.message : '');
	const previewState = $derived.by(() => {
		if (!isActiveStep) return 'inactive';
		if (!analysisPipeline) return 'waiting-for-payload';
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
