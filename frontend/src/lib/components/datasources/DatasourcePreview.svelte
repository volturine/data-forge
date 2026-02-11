<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { LoaderCircle, Play, Bug } from 'lucide-svelte';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import DataTable from '$lib/components/viewers/DataTable.svelte';

	interface Props {
		datasourceId: string;
		datasourceConfig?: Record<string, unknown> | null;
	}

	let { datasourceId, datasourceConfig = null }: Props = $props();

	let page = $state(1);
	let rowLimit = $state(100);
	let columnSearch = $state('');

	$effect(() => {
		if (!datasourceId) return;
		page = 1;
	});

	const query = createQuery(() => ({
		queryKey: ['datasource-preview', datasourceId, page, rowLimit, datasourceConfig],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const result = await previewStepData({
				analysis_id: '',
				datasource_id: datasourceId,
				pipeline_steps: [],
				target_step_id: 'source',
				row_limit: rowLimit,
				page,
				datasource_config: datasourceConfig
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

<div class="h-full flex flex-col">

	{#if isLoading}
		<div class="flex h-full flex-col items-center justify-center gap-3 text-fg-tertiary">
			<LoaderCircle size={18} class="animate-spin" />
			<p class="m-0 text-fg-tertiary">Loading</p>
		</div>
	{:else if error}
		<div class="flex h-full flex-col items-center justify-center gap-3 text-fg-tertiary">
			<Bug size={18} class="animate-spin" />
			<p class="m-0 text-fg-tertiary">Failed</p>
			<p class="m-0 text-fg-tertiary">{error.message}</p>
		</div>
	{:else}
		<div class="flex-1 overflow-hidden">
			<DataTable
				columns={data?.columns ?? []}
				data={data?.data ?? []}
				columnTypes={data?.column_types ?? {}}
				fillContainer
				bind:columnSearch
				showHeader
				showPagination
				pagination={{
					page,
					canPrev,
					canNext,
					onPrev: goPrev,
					onNext: goNext,
				}}
				showTypeBadges
			/>
		</div>
	{/if}
</div>
