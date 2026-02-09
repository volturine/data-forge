<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import DataTable from '$lib/components/viewers/DataTable.svelte';

	interface Props {
		datasourceId: string;
	}

	let { datasourceId }: Props = $props();

	let page = $state(1);
	let rowLimit = $state(100);
	let columnSearch = $state('');

	$effect(() => {
		if (!datasourceId) return;
		page = 1;
	});

	const query = createQuery(() => ({
		queryKey: ['datasource-preview', datasourceId, page, rowLimit],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const result = await previewStepData({
				analysis_id: '',
				datasource_id: datasourceId,
				pipeline_steps: [],
				target_step_id: 'source',
				row_limit: rowLimit,
				page
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
	{#if error}
		<div class="flex-1 flex items-center justify-center">
			<div class="text-center">
				<p class="m-0 mb-2 font-semibold text-error-fg">Failed to load preview</p>
				<p class="m-0 text-xs text-fg-tertiary">{error.message}</p>
			</div>
		</div>
	{:else}
		<div class="flex-1 overflow-hidden">
			<DataTable
				columns={data?.columns ?? []}
				data={data?.data ?? []}
				columnTypes={data?.column_types ?? {}}
				loading={isLoading}
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
					loading: isLoading
				}}
				showTypeBadges
			/>
		</div>
	{/if}
</div>
