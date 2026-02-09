<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import { applySteps } from '$lib/utils/pipeline';
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

	const pipelineKey = $derived(JSON.stringify(activePipeline));

	const query = createQuery(() => {
		return {
			queryKey: [
				'step-preview',
				analysisId,
				datasourceId,
				stepId,
				currentPage,
				rowLimit,
				pipelineKey
			],
			queryFn: async (): Promise<StepPreviewResponse> => {
				if (!isActiveStep) {
					throw new Error('Step is disabled');
				}
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
					resource_config: resourceConfig
				});
				if (result.isErr()) {
					throw new Error(result.error.message);
				}
				return result.value;
			},
			staleTime: Infinity
		};
	});

	const data = $derived(isActiveStep ? query.data : null);
	const isLoading = $derived(isActiveStep ? query.isLoading : false);
	const error = $derived(isActiveStep ? query.error : null);
	const totalPages = $derived(data ? Math.ceil(data.total_rows / rowLimit) : 0);
	const startRow = $derived((currentPage - 1) * rowLimit + 1);
	const endRow = $derived(data ? Math.min(currentPage * rowLimit, data.total_rows) : 0);

	function nextPage() {
		if (currentPage < totalPages) currentPage++;
	}

	function prevPage() {
		if (currentPage > 1) currentPage--;
	}
</script>

<div class="w-full my-2 overflow-hidden select-text bg-panel">
	{#if isLoading}
		<div
			class="flex flex-col items-center justify-center gap-3 p-8 pointer-events-none text-fg-tertiary"
		>
			<div class="spinner-md"></div>
			<p class="m-0 text-fg-tertiary">Loading preview...</p>
		</div>
	{:else if error}
		<div class="p-8 text-center">
			<p class="m-0 mb-2 font-semibold text-error-fg">Failed to load preview</p>
			<p class="m-0 text-fg-tertiary">{error.message}</p>
		</div>
	{:else if data?.columns?.length}
		<div
			class="flex justify-between items-center px-4 py-3 text-xs border-b text-fg-tertiary border-tertiary bg-panel-header"
		>
			<span>
				Showing {startRow.toLocaleString()}-{endRow.toLocaleString()} of {data.total_rows.toLocaleString()}
				rows
			</span>
			<input
				type="text"
				class="input-base input-compact border px-2 py-1 text-xs"
				placeholder="Filter columns"
				bind:value={columnSearch}
			/>
		</div>

		<DataTable
			columns={data.columns}
			data={data.data}
			columnTypes={data.column_types}
			bind:columnSearch
			showTypeBadges
			showFooter={false}
			density="compact"
			maxHeight="100"
		/>

		{#if totalPages > 1}
			<div
				class="flex justify-between items-center px-4 py-3 border-t border-tertiary bg-panel-header"
			>
				<button
					class="px-4 py-2 border cursor-pointer transition-all border-tertiary bg-panel hover:bg-hover hover:border-tertiary disabled:opacity-40 disabled:cursor-not-allowed"
					onclick={prevPage}
					disabled={currentPage === 1}
				>
					Previous
				</button>
				<span class="text-xs text-fg-tertiary">Page {currentPage} of {totalPages}</span>
				<button
					class="px-4 py-2 border cursor-pointer transition-all border-tertiary bg-panel hover:bg-hover hover:border-tertiary disabled:opacity-40 disabled:cursor-not-allowed"
					onclick={nextPage}
					disabled={currentPage >= totalPages}
				>
					Next
				</button>
			</div>
		{/if}
	{:else}
		<div class="p-8 text-center text-fg-muted">
			<p class="m-0">No data available</p>
		</div>
	{/if}
</div>
