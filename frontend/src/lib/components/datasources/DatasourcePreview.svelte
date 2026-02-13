<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import DataTable from '$lib/components/viewers/DataTable.svelte';

	interface Props {
		datasourceId: string;
		datasourceConfig?: Record<string, unknown>;
	}

	let { datasourceId, datasourceConfig = {} }: Props = $props();

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
		/>
	</div>
</div>
