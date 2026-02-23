<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import {
		previewStepData,
		type StepPreviewRequest,
		type StepPreviewResponse
	} from '$lib/api/compute';
	import DataTable from '$lib/components/common/DataTable.svelte';
	import ColumnStatsPanel from '$lib/components/datasources/ColumnStatsPanel.svelte';
	import type { DataSource } from '$lib/types/datasource';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import {
		buildAnalysisPipelinePayload,
		buildDatasourcePipelinePayload
	} from '$lib/utils/analysis-pipeline';

	interface Props {
		datasourceId: string;
		datasource?: DataSource | null;
		datasourceConfig?: Record<string, unknown>;
	}

	let { datasourceId, datasource, datasourceConfig = {} }: Props = $props();

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

	// Subscription: $derived can't reset pagination/state.
	$effect(() => {
		if (!datasourceId) return;
		void datasourceConfig;
		page = 1;
		statsOpen = false;
		statsColumn = null;
	});

	// Subscription: $derived can't reset pagination on pipeline changes.
	$effect(() => {
		if (!analysisPipeline) return;
		page = 1;
	});

	const resolvedDatasource = $derived.by(() => datasource ?? null);
	const analysisSourceId = $derived.by(() => {
		return (
			(datasourceConfig?.analysis_id as string | null | undefined) ??
			((resolvedDatasource?.config as Record<string, unknown> | null)?.analysis_id as
				| string
				| null
				| undefined) ??
			null
		);
	});
	const analysisPipeline = $derived.by(() => {
		const activeId = analysisStore.current?.id ?? null;
		if (analysisSourceId && activeId === analysisSourceId) {
			return buildAnalysisPipelinePayload(
				activeId,
				analysisStore.tabs,
				resolvedDatasource ? [resolvedDatasource] : []
			);
		}
		if (!resolvedDatasource) return null;
		return buildDatasourcePipelinePayload({
			datasource: resolvedDatasource,
			datasourceConfig: datasourceConfig ?? null
		});
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
			if (!analysisPipeline) {
				throw new Error('Analysis pipeline payload required for preview');
			}
			const request = {
				analysis_id: '',
				target_step_id: 'source',
				analysis_pipeline: analysisPipeline,
				row_limit: rowLimit,
				page,
				datasource_config: combinedConfig
			} satisfies StepPreviewRequest;
			const result = await previewStepData(request);
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
		{datasourceConfig}
		onClose={handleStatsClose}
	/>
</div>
