<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import { applySteps } from '$lib/utils/pipeline';
	import { hashPipeline } from '$lib/utils/hash';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import DataTable from '$lib/components/viewers/DataTable.svelte';

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

	let { analysisId, datasourceId, pipeline, stepId, rowLimit = 1000 }: Props = $props();
	let currentPage = $state(1);
	let columnSearch = $state('');

	let activePipeline = $derived(applySteps(pipeline));
	let isActiveStep = $derived(activePipeline.some((step) => step.id === stepId));
	const pipelineKey = $derived.by(() => hashPipeline(activePipeline));
	const datasourceConfig = $derived(analysisStore.activeTab?.datasource_config ?? {});
	const datasourceKey = $derived.by(() => {
		const config = datasourceConfig as Record<string, unknown>;
		const {
			time_travel_ui: _ui,
			output: _output,
			snapshot_id,
			snapshot_timestamp_ms,
			...rest
		} = config;
		return JSON.stringify({
			...rest,
			snapshot_id: snapshot_id ?? null,
			snapshot_timestamp_ms: snapshot_timestamp_ms ?? null
		});
	});
	const snapshotKey = $derived.by(() => {
		const config = datasourceConfig as Record<string, unknown>;
		const snapshotId = (config.snapshot_id as string | null | undefined) ?? null;
		const snapshotMs = (config.snapshot_timestamp_ms as number | null | undefined) ?? null;
		return `${snapshotId ?? 'latest'}:${snapshotMs ?? 0}`;
	});
	const runKey = $derived(`${analysisId}:${datasourceId}:${snapshotKey}:${rowLimit}:${stepId}`);
	const hasRun = $derived(analysisStore.previewRuns.get(runKey) ?? false);

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
			const resourceConfig = analysisStore.resourceConfig as unknown as Record<
				string,
				unknown
			> | null;
			const result = await previewStepData({
				analysis_id: analysisId,
				datasource_id: datasourceId,
				pipeline_steps: activePipeline,
				target_step_id: stepId,
				row_limit: rowLimit,
				page: currentPage,
				resource_config: resourceConfig,
				datasource_config: analysisStore.activeTab?.datasource_config ?? null
			});
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		},
		staleTime: Infinity,
		gcTime: Infinity,
		refetchOnMount: false,
		enabled: hasRun && isActiveStep
	}));

	const data = $derived(isActiveStep && hasRun ? query.data : null);
	const isLoading = $derived(isActiveStep && hasRun ? query.isFetching : false);
	const error = $derived(isActiveStep && hasRun ? query.error : null);
	const pageSize = $derived(data?.data?.length ?? 0);
	const canPrev = $derived(currentPage > 1);
	const canNext = $derived(pageSize === rowLimit);

	const resetKey = $derived(
		`${analysisId}-${datasourceId}-${stepId}-${rowLimit}-${pipelineKey}-${datasourceKey}`
	);
	$effect(() => {
		void resetKey;
		currentPage = 1;
	});

	function runPreview() {
		if (!isActiveStep) return;
		if (!hasRun) analysisStore.setPreviewRun(runKey, true);
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

<div class="inline-preview-table w-full h-100 overflow-hidden">
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
