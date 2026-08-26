<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import { applySteps } from '$lib/utils/pipeline';
	import { hashPipeline } from '$lib/utils/hash';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import {
		buildAnalysisPipelinePayload,
		buildDatasourceConfig
	} from '$lib/utils/analysis-pipeline';
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
	const datasourceConfig = $derived.by(() => {
		const config = buildDatasourceConfig({
			analysisId,
			tab: analysisStore.activeTab ?? null,
			tabs: analysisStore.tabs,
			datasources: datasourceStore.datasources
		});
		if (config) return config;
		const active = analysisStore.activeTab;
		if (!active) return {};
		return active.datasource.config;
	});
	const datasourceKey = $derived.by(() => {
		const config = datasourceConfig as Record<string, unknown>;
		const {
			time_travel_ui: _ui,
			output: _output,
			time_travel_snapshot_id,
			time_travel_snapshot_timestamp_ms,
			...rest
		} = config;
		return JSON.stringify({
			...rest,
			snapshot_id: time_travel_snapshot_id ?? null,
			snapshot_timestamp_ms: time_travel_snapshot_timestamp_ms ?? null
		});
	});
	const analysisPipeline = $derived.by(() => {
		if (!analysisId) return null;
		return buildAnalysisPipelinePayload(
			analysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
	});

	const query = createQuery(() => ({
		queryKey: [
			'step-preview',
			analysisId,
			datasourceId,
			stepId,
			currentPage,
			rowLimit,
			pipelineKey,
			datasourceKey
		],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const result = await previewStepData({
				analysis_pipeline: analysisPipeline!,
				tab_id: analysisStore.activeTab?.id ?? null,
				target_step_id: stepId,
				row_limit: rowLimit,
				page: currentPage,
				resource_config: analysisStore.resourceConfig
			});
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			schemaStore.syncPreviewSchema(stepId, result.value, pipelineKey);
			return result.value;
		},
		staleTime: Infinity,
		gcTime: Infinity,
		refetchOnMount: false,
		retry: false,
		enabled: isActiveStep && !!analysisPipeline && !analysisStore.previews.paused
	}));

	const data = $derived(isActiveStep ? query.data : null);
	const isLoading = $derived(isActiveStep ? query.isFetching : false);
	const error = $derived(isActiveStep ? query.error : null);
	const errorMessage = $derived(error instanceof Error ? error.message : '');
	const previewState = $derived.by(() => {
		if (!isActiveStep) return 'inactive';
		if (!analysisPipeline) return 'waiting-for-payload';
		if (analysisStore.previews.paused) return 'paused';
		if (isLoading) return 'loading';
		if (error) return 'error';
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
	data-preview-ready={data && !isLoading && !error && data.columns.length > 0 ? 'true' : undefined}
	data-preview-state={previewState}
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
