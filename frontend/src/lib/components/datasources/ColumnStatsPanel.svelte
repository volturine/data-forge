<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { BarChart3, X } from 'lucide-svelte';
	import { getColumnStats } from '$lib/api/datasource';
	import type { HistogramBin } from '$lib/api/datasource';

	interface Props {
		datasourceId: string;
		columnName: string | null;
		open: boolean;
		datasourceConfig?: Record<string, unknown> | null;
		onClose: () => void;
	}

	let { datasourceId, columnName, open, datasourceConfig = null, onClose }: Props = $props();

	const query = createQuery(() => ({
		queryKey: ['column-stats', datasourceId, columnName, datasourceConfig ?? null],
		queryFn: async () => {
			if (!columnName) {
				throw new Error('Column name required');
			}
			const result = await getColumnStats(datasourceId, columnName, {
				sample: true,
				datasource_config: datasourceConfig ?? undefined
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: open && !!columnName && !!datasourceId,
		staleTime: 30000
	}));

	const stats = $derived(query.data ?? null);
	const loading = $derived(query.isLoading);
	const error = $derived(query.error);

	const histMax = $derived(stats?.histogram ? Math.max(...stats.histogram.map((b) => b.count)) : 0);

	const topMax = $derived(
		stats?.top_values ? Math.max(...stats.top_values.map((v) => Number(v.count ?? 0))) : 0
	);

	function fmt(value: number | null | undefined): string {
		if (value === null || value === undefined) return '-';
		return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
	}

	function barPct(count: number, max: number): number {
		if (max === 0) return 0;
		return (count / max) * 100;
	}

	function histLabel(bin: HistogramBin): string {
		return `${fmt(bin.start)} – ${fmt(bin.end)}`;
	}
</script>

{#if open}
	<div class="absolute inset-x-0 bottom-0 z-40">
		<div class="border-t border-tertiary bg-panel animate-slide-up">
			<div class="flex items-center justify-between px-5 py-3 border-b border-tertiary">
				<div class="flex items-center gap-2">
					<BarChart3 size={16} />
					<h3 class="m-0 text-xs font-semibold">Column Stats</h3>
					{#if columnName}
						<span class="text-xs text-fg-muted font-mono">{columnName}</span>
					{/if}
					{#if stats}
						<span class="text-xs text-fg-muted">({stats.dtype})</span>
					{/if}
				</div>
				<button
					class="flex items-center justify-center border border-tertiary bg-transparent px-2 py-1 text-xs text-fg-secondary hover:bg-hover transition-colors"
					onclick={onClose}
					type="button"
				>
					<X size={14} />
				</button>
			</div>

			<div class="stats-scroll overflow-y-auto p-5">
				{#if loading}
					<div class="text-sm text-fg-muted">Computing stats...</div>
				{:else if error}
					<div class="error-box text-sm">
						{error instanceof Error ? error.message : 'Failed to load stats'}
					</div>
				{:else if stats}
					<div class="flex gap-6">
						<!-- Left: Core metrics -->
						<div class="stats-metrics">
							<!-- Overview section -->
							<div class="stats-section">
								<div class="stats-section-title">Overview</div>
								<div class="stats-row">
									<span class="stats-label">Rows</span>
									<span class="stats-value">{stats.count.toLocaleString()}</span>
								</div>
								<div class="stats-row">
									<span class="stats-label">Nulls</span>
									<span class="stats-value">
										{stats.null_count.toLocaleString()}
									</span>
								</div>
								<div class="stats-null-bar">
									<div
										class="stats-null-fill"
										style="width: {Math.min(stats.null_percentage, 100)}%"
									></div>
								</div>
								<div class="text-xs text-fg-muted mt-0.5">
									{fmt(stats.null_percentage)}% null
								</div>
								{#if stats.unique !== null && stats.unique !== undefined}
									<div class="stats-row mt-1">
										<span class="stats-label">Unique</span>
										<span class="stats-value">{stats.unique.toLocaleString()}</span>
									</div>
								{/if}
							</div>

							<!-- Numeric stats -->
							{#if stats.mean !== null && stats.mean !== undefined}
								<div class="stats-section">
									<div class="stats-section-title">Distribution</div>
									<div class="stats-row">
										<span class="stats-label">Mean</span>
										<span class="stats-value">{fmt(stats.mean)}</span>
									</div>
									{#if stats.median !== null && stats.median !== undefined}
										<div class="stats-row">
											<span class="stats-label">Median</span>
											<span class="stats-value">{fmt(stats.median)}</span>
										</div>
									{/if}
									{#if stats.std !== null && stats.std !== undefined}
										<div class="stats-row">
											<span class="stats-label">Std Dev</span>
											<span class="stats-value">{fmt(stats.std)}</span>
										</div>
									{/if}
									<div class="stats-row">
										<span class="stats-label">Min</span>
										<span class="stats-value">{stats.min}</span>
									</div>
									{#if stats.q25 !== null && stats.q25 !== undefined}
										<div class="stats-row">
											<span class="stats-label">Q25</span>
											<span class="stats-value">{fmt(stats.q25)}</span>
										</div>
									{/if}
									{#if stats.q75 !== null && stats.q75 !== undefined}
										<div class="stats-row">
											<span class="stats-label">Q75</span>
											<span class="stats-value">{fmt(stats.q75)}</span>
										</div>
									{/if}
									<div class="stats-row">
										<span class="stats-label">Max</span>
										<span class="stats-value">{stats.max}</span>
									</div>
								</div>
							{/if}

							<!-- Datetime stats -->
							{#if stats.mean === null && stats.min !== null && stats.min !== undefined && typeof stats.min === 'string'}
								<div class="stats-section">
									<div class="stats-section-title">Range</div>
									<div class="stats-row">
										<span class="stats-label">Min</span>
										<span class="stats-value font-mono text-xs">{stats.min}</span>
									</div>
									<div class="stats-row">
										<span class="stats-label">Max</span>
										<span class="stats-value font-mono text-xs">{stats.max}</span>
									</div>
								</div>
							{/if}

							<!-- Boolean stats -->
							{#if stats.true_count !== null && stats.true_count !== undefined}
								{@const total = stats.true_count + (stats.false_count ?? 0)}
								{@const truePct = total > 0 ? (stats.true_count / total) * 100 : 0}
								<div class="stats-section">
									<div class="stats-section-title">Boolean Distribution</div>
									<div class="stats-bool-bar">
										<div class="stats-bool-true" style="width: {truePct}%"></div>
									</div>
									<div class="flex justify-between text-xs mt-1">
										<span class="text-accent-primary"
											>True: {stats.true_count.toLocaleString()}</span
										>
										<span class="text-fg-muted"
											>False: {(stats.false_count ?? 0).toLocaleString()}</span
										>
									</div>
								</div>
							{/if}

							<!-- String length stats -->
							{#if stats.min_length !== null && stats.min_length !== undefined}
								<div class="stats-section">
									<div class="stats-section-title">String Lengths</div>
									<div class="stats-row">
										<span class="stats-label">Min</span>
										<span class="stats-value">{stats.min_length}</span>
									</div>
									<div class="stats-row">
										<span class="stats-label">Avg</span>
										<span class="stats-value">{fmt(stats.avg_length)}</span>
									</div>
									<div class="stats-row">
										<span class="stats-label">Max</span>
										<span class="stats-value">{stats.max_length}</span>
									</div>
								</div>
							{/if}
						</div>

						<!-- Right: Visualizations -->
						<div class="stats-viz">
							<!-- Histogram for numeric columns -->
							{#if stats.histogram && stats.histogram.length > 1}
								<div class="stats-section">
									<div class="stats-section-title">Distribution</div>
									<div class="stats-histogram">
										{#each stats.histogram as bin (bin.start)}
											<div
												class="stats-hist-bar"
												title="{histLabel(bin)}: {bin.count.toLocaleString()}"
											>
												<div
													class="stats-hist-fill"
													style="height: {barPct(bin.count, histMax)}%"
												></div>
											</div>
										{/each}
									</div>
									<div class="flex justify-between text-xs text-fg-muted mt-1">
										<span>{fmt(stats.histogram[0].start)}</span>
										<span>{fmt(stats.histogram[stats.histogram.length - 1].end)}</span>
									</div>
								</div>
							{/if}

							<!-- Top values for string columns -->
							{#if stats.top_values && stats.top_values.length > 0}
								<div class="stats-section">
									<div class="stats-section-title">Top Values</div>
									<div class="stats-top-values">
										{#each stats.top_values as item, i (i)}
											{@const val = String(item[stats.column] ?? '')}
											{@const cnt = Number(item.count ?? 0)}
											<div class="stats-top-row">
												<div class="stats-top-info">
													<span class="stats-top-label" title={val}>{val}</span>
													<span class="text-xs text-fg-muted">{cnt.toLocaleString()}</span>
												</div>
												<div class="stats-top-bar-bg">
													<div
														class="stats-top-bar-fill"
														style="width: {barPct(cnt, topMax)}%"
													></div>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.stats-scroll {
		height: 320px;
	}

	.stats-metrics {
		min-width: 240px;
		flex-shrink: 0;
	}

	.stats-viz {
		flex: 1;
		min-width: 0;
	}

	.stats-section {
		margin-bottom: 16px;
	}

	.stats-section-title {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-fg-muted);
		margin-bottom: 6px;
	}

	.stats-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		padding: 2px 0;
	}

	.stats-label {
		font-size: 12px;
		color: var(--color-fg-muted);
	}

	.stats-value {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-fg-primary);
		font-family: var(--font-mono);
	}

	/* Null percentage bar */
	.stats-null-bar {
		height: 6px;
		background: var(--color-bg-tertiary);
		border: 1px solid var(--color-border-tertiary);
		margin-top: 4px;
		overflow: hidden;
	}

	.stats-null-fill {
		height: 100%;
		background: var(--color-accent-primary);
		transition: width 300ms ease;
	}

	/* Boolean bar */
	.stats-bool-bar {
		height: 8px;
		background: var(--color-bg-tertiary);
		border: 1px solid var(--color-border-tertiary);
		overflow: hidden;
	}

	.stats-bool-true {
		height: 100%;
		background: var(--color-accent-primary);
		transition: width 300ms ease;
	}

	/* Histogram */
	.stats-histogram {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		height: 120px;
	}

	.stats-hist-bar {
		flex: 1;
		height: 100%;
		display: flex;
		align-items: flex-end;
		cursor: default;
	}

	.stats-hist-fill {
		width: 100%;
		background: var(--color-accent-primary);
		opacity: 0.7;
		min-height: 1px;
		transition: height 300ms ease;
	}

	.stats-hist-bar:hover .stats-hist-fill {
		opacity: 1;
	}

	/* Top values */
	.stats-top-values {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.stats-top-row {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.stats-top-info {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}

	.stats-top-label {
		font-size: 12px;
		font-family: var(--font-mono);
		color: var(--color-fg-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 200px;
	}

	.stats-top-bar-bg {
		height: 6px;
		background: var(--color-bg-tertiary);
		border: 1px solid var(--color-border-tertiary);
		overflow: hidden;
	}

	.stats-top-bar-fill {
		height: 100%;
		background: var(--color-accent-primary);
		opacity: 0.7;
		transition: width 300ms ease;
	}
</style>
