<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { onDestroy } from 'svelte';
	import {
		previewStepData,
		throwIfAborted,
		type StepPreviewRequest,
		type StepPreviewResponse
	} from '$lib/api/compute';
	import DataTable from '$lib/components/common/DataTable.svelte';
	import ColumnStatsPanel from '$lib/components/datasources/ColumnStatsPanel.svelte';
	import { datasourceHasMaterializedSnapshot, type DataSource } from '$lib/types/datasource';
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import { buildDatasourcePreviewPipelinePayload } from '$lib/utils/analysis-pipeline';
	import { toComputeError } from '$lib/utils/compute-error';
	import { css } from '$lib/styles/panda';

	interface Props {
		datasourceId: string;
		datasource?: DataSource | null;
		datasourceConfig?: Record<string, unknown>;
	}

	let { datasourceId, datasource, datasourceConfig = {} }: Props = $props();

	const ns = useNamespace();

	let page = $state(1);
	let rowLimit = $state(100);
	let columnSearch = $state('');
	let statsColumn = $state<string | null>(null);
	let statsOpen = $state(false);
	let previewRequestKey: string | null = null;
	let previewRequestController = new AbortController();

	function previewSignal(request: StepPreviewRequest): AbortSignal {
		const nextKey = JSON.stringify(request);
		if (previewRequestKey !== nextKey || previewRequestController.signal.aborted) {
			if (previewRequestKey !== null && !previewRequestController.signal.aborted) {
				previewRequestController.abort();
			}
			previewRequestKey = nextKey;
			previewRequestController = new AbortController();
		}
		return previewRequestController.signal;
	}

	onDestroy(() => previewRequestController.abort());

	function handleColumnStats(columnName: string) {
		statsColumn = columnName;
		statsOpen = true;
	}

	function handleStatsClose() {
		statsOpen = false;
	}

	const resolvedDatasource = $derived(datasource ?? null);
	const canPreviewDatasource = $derived(
		!!resolvedDatasource && datasourceHasMaterializedSnapshot(resolvedDatasource)
	);
	const analysisPipeline = $derived.by(() => {
		if (!resolvedDatasource) return null;
		if (!datasourceConfig) return null;
		return buildDatasourcePreviewPipelinePayload({
			datasource: resolvedDatasource,
			datasourceConfig
		});
	});

	const previewRequestState = $derived.by(() => {
		if (!analysisPipeline) return null;
		return {
			request: {
				target_step_id: 'source',
				datasource_id: datasourceId,
				analysis_pipeline: analysisPipeline,
				row_limit: rowLimit,
				page
			} satisfies StepPreviewRequest
		};
	});

	const query = createQuery(() => ({
		// Keep execution tied to the same datasource RID and complete command
		// represented by the cache key, even if page/config state changes mid-fetch.
		queryKey: [
			'datasource-preview',
			ns.ready ? ns.value : null,
			datasourceId,
			previewRequestState
		] as const,
		queryFn: async ({ queryKey }): Promise<StepPreviewResponse> => {
			const state = queryKey[3];
			if (!state) throw new Error('Datasource preview command is not ready');
			const { request } = state;
			const signal = previewSignal(request);
			const result = await previewStepData(request, { signal });
			throwIfAborted(signal);
			if (result.isErr()) {
				throw toComputeError(result.error);
			}
			return result.value;
		},
		staleTime: 30000,
		refetchOnMount: false,
		retry: false,
		enabled:
			ns.ready && !!datasourceId && !!previewRequestState && !ns.switching && canPreviewDatasource
	}));

	const data = $derived(query.data);
	// `isLoading` only describes the first fetch.  Preview data can already be
	// rendered while TanStack Query is fetching a new page/config, so use the
	// fetching state for the UI readiness contract just like inline previews do.
	const isLoading = $derived(query.isFetching);
	const error = $derived(query.error);
	const errorMessage = $derived(error instanceof Error ? error.message : '');
	const previewState = $derived.by(() => {
		if (!canPreviewDatasource) return 'inactive';
		if (!analysisPipeline) return 'waiting-for-payload';
		if (error) return 'error';
		if (isLoading) return 'loading';
		if (data) return 'ready';
		return 'idle';
	});

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
	data-testid="datasource-preview"
	data-preview-ready={data && !isLoading && !error ? 'true' : undefined}
	data-preview-state={previewState}
	data-preview-query-status={query.status}
	data-preview-fetch-status={query.fetchStatus}
	data-preview-has-data={query.data ? 'true' : 'false'}
	data-preview-error={errorMessage || undefined}
>
	{#if !canPreviewDatasource}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				height: 'full',
				padding: '6',
				textAlign: 'center',
				color: 'fg.muted'
			})}
		>
			Build this output before previewing or refreshing its schema.
		</div>
	{:else}
		<div class={css({ overflow: 'hidden', height: 'full', flex: '1', minHeight: '0' })}>
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
	{/if}
</div>
