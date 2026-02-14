<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import DataTable from '$lib/components/viewers/DataTable.svelte';
	import ColumnStatsPanel from '$lib/components/datasources/ColumnStatsPanel.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';

	interface Props {
		datasourceId: string;
		datasourceConfig?: Record<string, unknown>;
	}

	let { datasourceId, datasourceConfig = {} }: Props = $props();

	let page = $state(1);
	let rowLimit = $state(100);
	let columnSearch = $state('');
	let statsColumn = $state<string | null>(null);
	let statsOpen = $state(false);

	function handleColumnStats(columnName: string) {
		statsColumn = columnName;
		statsOpen = true;
	}

	function handleStatsClose() {
		statsOpen = false;
	}

	$effect(() => {
		// Reset pagination and close stats when datasource changes; requires effect to update state.
		if (!datasourceId) return;
		page = 1;
		statsOpen = false;
		statsColumn = null;
	});

	$effect(() => {
		// Reset pagination when live analysis pipeline changes; requires effect to update state.
		if (!analysisPipeline) return;
		page = 1;
	});

	const datasource = $derived.by(() => datasourceStore.getDatasource(datasourceId) ?? null);
	const analysisSourceId = $derived.by(() => {
		return (
			(datasourceConfig?.analysis_id as string | null | undefined) ??
			((datasource?.config as Record<string, unknown> | null)?.analysis_id as
				| string
				| null
				| undefined) ??
			null
		);
	});
	const analysisPipeline = $derived.by(() => {
		if (!analysisSourceId) return null;
		const activeId = analysisStore.current?.id ?? null;
		if (!activeId || activeId !== analysisSourceId) return null;
		return buildAnalysisPipelinePayload(activeId, analysisStore.tabs, datasourceStore.datasources);
	});

	const query = createQuery(() => ({
		queryKey: [
			'datasource-preview',
			datasourceId,
			page,
			rowLimit,
			datasourceConfig,
			analysisPipeline
		],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const combinedConfig = analysisPipeline
				? { ...(datasourceConfig ?? {}), analysis_pipeline: analysisPipeline }
				: datasourceConfig;
			const result = await previewStepData({
				analysis_id: '',
				datasource_id: datasourceId,
				pipeline_steps: [],
				target_step_id: 'source',
				row_limit: rowLimit,
				page,
				datasource_config: combinedConfig
			});
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		},
		staleTime: 30000,
		enabled: !!datasourceId
	}));

	const data = $derived(query.data);
	const isLoading = $derived(query.isLoading);
	const error = $derived(query.error);

	const canPrev = $derived(page > 1);
	const pageSize = $derived(data?.data?.length ?? 0);
	const canNext = $derived(pageSize === rowLimit);

	function goPrev() {
		if (!canPrev) return;
		page -= 1;
	}

	function goNext() {
		if (!canNext) return;
		page += 1;
	}
</script>

<div class="relative h-full flex flex-col">
	<div class="overflow-hidden h-full">
		<DataTable
			columns={data?.columns ?? []}
			data={data?.data ?? []}
			columnTypes={data?.column_types ?? {}}
			loading={isLoading}
			{error}
			fillContainer
			bind:columnSearch
			showHeader
			showPagination
			pagination={{
				page,
				canPrev,
				canNext,
				onPrev: goPrev,
				onNext: goNext
			}}
			showTypeBadges
			onColumnStats={handleColumnStats}
		/>
	</div>
	<ColumnStatsPanel
		{datasourceId}
		columnName={statsColumn}
		open={statsOpen}
		onClose={handleStatsClose}
	/>
</div>
