<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { BarChart3, X } from 'lucide-svelte';
	import { getColumnStats } from '$lib/api/datasource';

	interface Props {
		datasourceId: string;
		columnName: string | null;
		open: boolean;
		onClose: () => void;
	}

	let { datasourceId, columnName, open, onClose }: Props = $props();

	const query = createQuery(() => ({
		queryKey: ['column-stats', datasourceId, columnName],
		queryFn: async () => {
			if (!columnName) {
				throw new Error('Column name required');
			}
			const result = await getColumnStats(datasourceId, columnName, { sample: true });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: open && !!columnName && !!datasourceId,
		staleTime: 30000
	}));

	const stats = $derived(query.data ?? null);
	const loading = $derived(query.isLoading);
	const error = $derived(query.error);

	function formatNumber(value: number | null | undefined): string {
		if (value === null || value === undefined) return '-';
		return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
	}
</script>

{#if open}
	<div class="fixed inset-x-0 bottom-0 z-40">
		<div class="border-t border-tertiary bg-panel animate-slide-up">
			<div class="flex items-center justify-between px-5 py-4 border-b border-tertiary">
				<div class="flex items-center gap-2">
					<BarChart3 size={18} />
					<h3 class="m-0 text-sm font-semibold">Column Stats</h3>
					{#if columnName}
						<span class="text-xs text-fg-muted font-mono">{columnName}</span>
					{/if}
				</div>
				<button
					class="flex items-center justify-center border border-tertiary bg-transparent px-2 py-1 text-xs text-fg-secondary hover:bg-hover"
					onclick={onClose}
					type="button"
				>
					<X size={14} />
				</button>
			</div>

			<div class="max-h-80 overflow-y-auto p-5">
				{#if loading}
					<div class="text-sm text-fg-muted">Computing stats...</div>
				{:else if error}
					<div class="error-box text-sm">
						{error instanceof Error ? error.message : 'Failed to load stats'}
					</div>
				{:else if stats}
					<div class="grid gap-4 md:grid-cols-3">
						<div class="border border-tertiary bg-tertiary p-3">
							<div class="text-xs text-fg-muted">Type</div>
							<div class="text-sm font-semibold">{stats.dtype}</div>
						</div>
						<div class="border border-tertiary bg-tertiary p-3">
							<div class="text-xs text-fg-muted">Count</div>
							<div class="text-sm font-semibold">{stats.count.toLocaleString()}</div>
						</div>
						<div class="border border-tertiary bg-tertiary p-3">
							<div class="text-xs text-fg-muted">Nulls</div>
							<div class="text-sm font-semibold">
								{stats.null_count.toLocaleString()} ({formatNumber(stats.null_percentage)}%)
							</div>
						</div>
						{#if stats.mean !== null && stats.mean !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Mean</div>
								<div class="text-sm font-semibold">{formatNumber(stats.mean)}</div>
							</div>
						{/if}
						{#if stats.median !== null && stats.median !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Median</div>
								<div class="text-sm font-semibold">{formatNumber(stats.median)}</div>
							</div>
						{/if}
						{#if stats.std !== null && stats.std !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Std Dev</div>
								<div class="text-sm font-semibold">{formatNumber(stats.std)}</div>
							</div>
						{/if}
						{#if stats.q25 !== null && stats.q25 !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Q25</div>
								<div class="text-sm font-semibold">{formatNumber(stats.q25)}</div>
							</div>
						{/if}
						{#if stats.q75 !== null && stats.q75 !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Q75</div>
								<div class="text-sm font-semibold">{formatNumber(stats.q75)}</div>
							</div>
						{/if}
						{#if stats.min !== null && stats.min !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Min</div>
								<div class="text-sm font-semibold">{stats.min}</div>
							</div>
						{/if}
						{#if stats.max !== null && stats.max !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Max</div>
								<div class="text-sm font-semibold">{stats.max}</div>
							</div>
						{/if}
						{#if stats.unique !== null && stats.unique !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Unique</div>
								<div class="text-sm font-semibold">{stats.unique.toLocaleString()}</div>
							</div>
						{/if}
						{#if stats.true_count !== null && stats.true_count !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">True</div>
								<div class="text-sm font-semibold">{stats.true_count.toLocaleString()}</div>
							</div>
						{/if}
						{#if stats.false_count !== null && stats.false_count !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">False</div>
								<div class="text-sm font-semibold">{stats.false_count.toLocaleString()}</div>
							</div>
						{/if}
						{#if stats.min_length !== null && stats.min_length !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Min Length</div>
								<div class="text-sm font-semibold">{stats.min_length}</div>
							</div>
						{/if}
						{#if stats.max_length !== null && stats.max_length !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Max Length</div>
								<div class="text-sm font-semibold">{stats.max_length}</div>
							</div>
						{/if}
						{#if stats.avg_length !== null && stats.avg_length !== undefined}
							<div class="border border-tertiary bg-tertiary p-3">
								<div class="text-xs text-fg-muted">Avg Length</div>
								<div class="text-sm font-semibold">{formatNumber(stats.avg_length)}</div>
							</div>
						{/if}
					</div>

					{#if stats.top_values && stats.top_values.length > 0}
						<div class="mt-4 border border-tertiary bg-tertiary">
							<div
								class="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-fg-muted border-b border-tertiary"
							>
								Top Values
							</div>
							<div class="p-3 space-y-1 text-xs">
								{#each stats.top_values as item (item[stats.column])}
									<div class="flex items-center justify-between">
										<span class="font-mono text-fg-primary">{item[stats.column]}</span>
										<span class="text-fg-muted">{item.count}</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/if}
