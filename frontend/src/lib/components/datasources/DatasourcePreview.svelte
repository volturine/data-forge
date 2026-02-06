<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { Table, FileBracesCorner } from 'lucide-svelte';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import DataTable from '$lib/components/viewers/DataTable.svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { resolveColumnType } from '$lib/utils/columnTypes';

	interface Props {
		datasourceId: string;
		datasourceName: string;
	}

	let { datasourceId, datasourceName }: Props = $props();

	let viewMode = $state<'data' | 'schema'>('data');
	let page = $state(1);
	let rowLimit = $state(100);

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

	const schema = $derived(
		data
			? data.columns.map((name) => ({
					name,
					dtype: resolveColumnType(data.column_types?.[name])
				}))
			: []
	);

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

<div class="rounded-md overflow-hidden" style="background: var(--bg-primary);">
	<div class="flex justify-between items-center px-4 py-3 border-b" style="background: var(--bg-tertiary); border-color: var(--border-primary);">
		<h3 class="m-0 text-sm font-semibold truncate" style="color: var(--fg-primary);">{datasourceName}</h3>
		<div class="flex gap-1 shrink-0">
			<button
				class="toggle-btn"
				class:active={viewMode === 'data'}
				onclick={() => (viewMode = 'data')}
			>
				<Table size={14} />
				Data
			</button>
			<button
				class="toggle-btn"
				class:active={viewMode === 'schema'}
				onclick={() => (viewMode = 'schema')}
			>
				<FileBracesCorner size={14} />
				Schema
			</button>
		</div>
	</div>

	{#if viewMode === 'data'}
		{#if error}
			<div class="p-8 text-center">
				<p class="m-0 mb-2 font-semibold" style="color: var(--error-fg);">Failed to load preview</p>
				<p class="m-0 text-xs" style="color: var(--fg-tertiary);">{error.message}</p>
			</div>
		{:else}
			<div class="flex items-center gap-3 px-4 py-3 border-b" style="background: var(--bg-secondary); border-color: var(--border-primary);">
				<button class="page-btn" onclick={goPrev} disabled={!canPrev || isLoading}> Prev </button>
				<span class="text-xs" style="color: var(--fg-tertiary);">Page {page}</span>
				<button class="page-btn" onclick={goNext} disabled={!canNext || isLoading}> Next </button>
			</div>
			<DataTable
				columns={data?.columns ?? []}
				data={data?.data ?? []}
				columnTypes={data?.column_types ?? {}}
				loading={isLoading}
			/>
		{/if}
	{:else}
		<div class="max-h-[300px] overflow-y-auto">
			{#if isLoading}
				<div class="p-8 text-center pointer-events-none" style="color: var(--fg-tertiary);">Loading schema...</div>
			{:else if error}
				<div class="p-8 text-center">
					<p class="m-0 mb-2 font-semibold" style="color: var(--error-fg);">Failed to load schema</p>
					<p class="m-0 text-xs" style="color: var(--fg-tertiary);">{error.message}</p>
				</div>
			{:else}
				<div class="grid grid-cols-2 px-4 py-2 text-xs font-semibold sticky top-0 border-b" style="background: var(--bg-tertiary); border-color: var(--border-primary); color: var(--fg-muted);">
					<span>Column</span>
					<span>Type</span>
				</div>
				{#each schema as column (column.name)}
					<div class="schema-row">
						<span class="font-mono text-[0.8125rem]" style="color: var(--fg-primary);">{column.name}</span>
						<ColumnTypeBadge columnType={column.dtype} size="xs" showIcon={true} />
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>

<style>
	.toggle-btn {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.375rem 0.75rem;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--fg-tertiary);
		font-size: 0.75rem;
		font-weight: 500;
		cursor: pointer;
	}
	.toggle-btn:hover {
		background: var(--bg-hover);
		color: var(--fg-primary);
	}
	.toggle-btn.active {
		background: var(--accent-bg);
		color: var(--accent-fg);
		border-color: var(--accent-border);
	}
	.page-btn {
		padding: 0.25rem 0.6rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-primary);
		background: var(--bg-primary);
		color: var(--fg-primary);
		font-size: 0.75rem;
		cursor: pointer;
	}
	.page-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.schema-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		padding: 0.5rem 1rem;
		border-bottom: 1px solid var(--border-primary);
	}
	.schema-row:hover {
		background: var(--bg-hover);
	}
	.schema-row:last-child {
		border-bottom: none;
	}
</style>
