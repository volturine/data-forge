<script lang="ts">
	interface Props {
		rowCount: number;
		columnCount: number;
		stats?: Record<string, { mean?: number; min?: number; max?: number; nullCount?: number }>;
	}

	import { BarChart3, Binary, ListChecks } from 'lucide-svelte';

	let { rowCount, columnCount, stats }: Props = $props();

	let hasStats = $derived(stats && Object.keys(stats).length > 0);
</script>

<div class="stats-panel overflow-hidden border bg-panel border-tertiary">
	<div class="px-5 py-4 border-b border-tertiary bg-tertiary">
		<h3 class="m-0">Summary Statistics</h3>
	</div>

	<div class="stats-summary grid gap-4 p-5">
		<div class="flex items-center gap-4 p-4 border bg-tertiary border-tertiary">
			<BarChart3 size={24} class="text-fg-primary" />
			<div class="flex-1">
				<div class="text-xs font-medium uppercase tracking-wider mb-1 text-fg-muted">
					Total Rows
				</div>
				<div class="text-2xl font-bold leading-none text-fg-primary">
					{rowCount.toLocaleString()}
				</div>
			</div>
		</div>

		<div class="flex items-center gap-4 p-4 border bg-tertiary border-tertiary">
			<ListChecks size={24} class="text-fg-primary" />
			<div class="flex-1">
				<div class="text-xs font-medium uppercase tracking-wider mb-1 text-fg-muted">
					Total Columns
				</div>
				<div class="text-2xl font-bold leading-none text-fg-primary">
					{columnCount.toLocaleString()}
				</div>
			</div>
		</div>

		<div class="flex items-center gap-4 p-4 border bg-tertiary border-tertiary">
			<Binary size={24} class="text-fg-primary" />
			<div class="flex-1">
				<div class="text-xs font-medium uppercase tracking-wider mb-1 text-fg-muted">
					Data Points
				</div>
				<div class="text-2xl font-bold leading-none text-fg-primary">
					{(rowCount * columnCount).toLocaleString()}
				</div>
			</div>
		</div>
	</div>

	{#if hasStats && stats}
		<div class="px-5 pb-5">
			<h4 class="m-0 mb-4 text-sm font-semibold uppercase tracking-wider text-fg-muted">
				Column Statistics
			</h4>
			<div class="stats-columns grid gap-3">
				{#each Object.entries(stats) as [column, columnStats] (column)}
					<div class="p-3 border bg-tertiary border-tertiary">
						<div
							class="text-sm font-semibold font-mono mb-2 pb-2 border-b text-fg-primary border-tertiary"
						>
							{column}
						</div>
						<div class="flex flex-col gap-1">
							{#if columnStats.mean !== undefined}
								<div class="flex justify-between text-sm">
									<span class="font-medium text-fg-muted">Mean:</span>
									<span class="font-semibold font-mono text-fg-primary">
										{columnStats.mean.toFixed(2)}
									</span>
								</div>
							{/if}
							{#if columnStats.min !== undefined}
								<div class="flex justify-between text-sm">
									<span class="font-medium text-fg-muted">Min:</span>
									<span class="font-semibold font-mono text-fg-primary">
										{columnStats.min.toLocaleString()}
									</span>
								</div>
							{/if}
							{#if columnStats.max !== undefined}
								<div class="flex justify-between text-sm">
									<span class="font-medium text-fg-muted">Max:</span>
									<span class="font-semibold font-mono text-fg-primary">
										{columnStats.max.toLocaleString()}
									</span>
								</div>
							{/if}
							{#if columnStats.nullCount !== undefined && columnStats.nullCount > 0}
								<div class="flex justify-between text-sm">
									<span class="font-medium text-fg-muted">Nulls:</span>
									<span class="font-semibold font-mono text-error-fg">
										{columnStats.nullCount.toLocaleString()}
									</span>
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
