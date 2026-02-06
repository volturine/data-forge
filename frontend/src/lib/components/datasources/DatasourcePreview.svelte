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

<div class="rounded-md overflow-hidden bg-[var(--bg-primary)]">
	<div
		class="flex justify-between items-center px-4 py-3 border-b bg-[var(--bg-tertiary)] border-[var(--border-primary)]"
	>
		<h3 class="m-0 text-sm font-semibold truncate text-[var(--fg-primary)]">{datasourceName}</h3>
		<div class="flex gap-1 shrink-0">
			<button
				class="flex items-center gap-1.5 py-1.5 px-3 border border-transparent rounded-[var(--radius-sm)] bg-transparent text-[var(--fg-tertiary)] text-xs font-medium cursor-pointer transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--fg-primary)]"
				class:!bg-[var(--accent-bg)]={viewMode === 'data'}
				class:!text-[var(--accent-fg)]={viewMode === 'data'}
				class:!border-[var(--accent-border)]={viewMode === 'data'}
				onclick={() => (viewMode = 'data')}
			>
				<Table size={14} />
				Data
			</button>
			<button
				class="flex items-center gap-1.5 py-1.5 px-3 border border-transparent rounded-[var(--radius-sm)] bg-transparent text-[var(--fg-tertiary)] text-xs font-medium cursor-pointer transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--fg-primary)]"
				class:!bg-[var(--accent-bg)]={viewMode === 'schema'}
				class:!text-[var(--accent-fg)]={viewMode === 'schema'}
				class:!border-[var(--accent-border)]={viewMode === 'schema'}
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
				<p class="m-0 mb-2 font-semibold text-[var(--error-fg)]">Failed to load preview</p>
				<p class="m-0 text-xs text-[var(--fg-tertiary)]">{error.message}</p>
			</div>
		{:else}
			<div
				class="flex items-center gap-3 px-4 py-3 border-b bg-[var(--bg-secondary)] border-[var(--border-primary)]"
			>
				<button
					class="py-1 px-2.5 rounded-[var(--radius-sm)] border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--fg-primary)] text-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
					onclick={goPrev}
					disabled={!canPrev || isLoading}
				>
					Prev
				</button>
				<span class="text-xs text-[var(--fg-tertiary)]">Page {page}</span>
				<button
					class="py-1 px-2.5 rounded-[var(--radius-sm)] border border-[var(--border-primary)] bg-[var(--bg-primary)] text-[var(--fg-primary)] text-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
					onclick={goNext}
					disabled={!canNext || isLoading}
				>
					Next
				</button>
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
				<div class="p-8 text-center pointer-events-none text-[var(--fg-tertiary)]">
					Loading schema...
				</div>
			{:else if error}
				<div class="p-8 text-center">
					<p class="m-0 mb-2 font-semibold text-[var(--error-fg)]">Failed to load schema</p>
					<p class="m-0 text-xs text-[var(--fg-tertiary)]">{error.message}</p>
				</div>
			{:else}
				<div
					class="grid grid-cols-2 px-4 py-2 text-xs font-semibold sticky top-0 border-b bg-[var(--bg-tertiary)] border-[var(--border-primary)] text-[var(--fg-muted)]"
				>
					<span>Column</span>
					<span>Type</span>
				</div>
				{#each schema as column (column.name)}
					<div
						class="grid grid-cols-2 py-2 px-4 border-b border-[var(--border-primary)] last:border-b-0 hover:bg-[var(--bg-hover)]"
					>
						<span class="font-mono text-[0.8125rem] text-[var(--fg-primary)]">{column.name}</span>
						<ColumnTypeBadge columnType={column.dtype} size="xs" showIcon={true} />
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>
