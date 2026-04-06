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
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import {
		buildAnalysisPipelinePayload,
		buildDatasourcePipelinePayload
	} from '$lib/utils/analysis-pipeline';
	import { css } from '$lib/styles/panda';

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

	const resolvedDatasource = $derived(datasource ?? null);
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
				datasourceStore.datasources
			);
		}
		if (!resolvedDatasource) return null;
		return buildDatasourcePipelinePayload({
			datasource: resolvedDatasource,
			datasourceConfig: datasourceConfig ?? { branch: 'master' }
		});
	});

	const configKey = $derived(JSON.stringify(datasourceConfig));
	const pipelineKey = $derived(JSON.stringify(analysisPipeline));

	// Subscription: $derived can't reset pagination/state.
	$effect(() => {
		if (!datasourceId) return;
		void configKey;
		page = 1;
		statsOpen = false;
		statsColumn = null;
	});

	// Subscription: $derived can't reset pagination on pipeline changes.
	$effect(() => {
		if (!pipelineKey) return;
		page = 1;
	});

	const query = createQuery(() => ({
		queryKey: ['datasource-preview', datasourceId, page, rowLimit, configKey, pipelineKey],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const pipeline = analysisPipeline!;
			const request = {
				analysis_id: '',
				target_step_id: 'source',
				analysis_pipeline: pipeline,
				row_limit: rowLimit,
				page
			} satisfies StepPreviewRequest;
			const result = await previewStepData(request);
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		},
		staleTime: 30000,
		enabled: !!datasourceId && !!analysisPipeline
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

<div
	class={css({
		position: 'relative',
		height: 'full',
		display: 'flex',
		flexDirection: 'column'
	})}
	data-preview-ready={data && !isLoading ? 'true' : undefined}
>
	<div class={css({ overflow: 'hidden', height: 'full' })}>
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
