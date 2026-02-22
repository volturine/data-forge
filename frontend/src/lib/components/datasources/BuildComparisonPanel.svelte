<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { listEngineRuns, type EngineRun } from '$lib/api/engine-runs';
	import { compareDatasourceSnapshots, listIcebergSnapshots } from '$lib/api/datasource';
	import type { SnapshotCompareResponse } from '$lib/api/datasource';
	import type { DataSource } from '$lib/types/datasource';
	import DataTable from '$lib/components/viewers/DataTable.svelte';
	import { GitCompareArrows, RefreshCw, X, Plus, Minus, Search } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { buildSnapshotMap } from '$lib/utils/build-snapshot-map';

	interface Props {
		datasource: DataSource;
	}

	let { datasource }: Props = $props();

	const selected = new SvelteSet<string>();
	let comparison = $state<SnapshotCompareResponse | null>(null);
	let comparing = $state(false);
	let compareError = $state<string | null>(null);
	let runSearch = $state('');
	let rowLimit = $state(100);

	const runsQuery = createQuery(() => ({
		queryKey: ['engine-runs', datasource.id],
		queryFn: async () => {
			const result = await listEngineRuns({ datasource_id: datasource.id, limit: 50 });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const snapshotsQuery = createQuery(() => ({
		queryKey: ['iceberg-snapshots', datasource.id],
		queryFn: async () => {
			const result = await listIcebergSnapshots(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value.snapshots;
		},
		enabled: datasource.source_type === 'iceberg'
	}));

	const runs = $derived.by(() =>
		(runsQuery.data ?? []).filter(
			(run) =>
				(run.kind === 'datasource_update' || run.kind === 'datasource_create') &&
				run.status === 'success'
		)
	);

	const visibleRuns = $derived.by(() => {
		const q = runSearch.trim().toLowerCase();
		if (!q) return runs;
		return runs.filter((run) => {
			const created = formatDate(run.created_at).toLowerCase();
			return (
				run.id.toLowerCase().includes(q) ||
				run.kind.toLowerCase().includes(q) ||
				created.includes(q)
			);
		});
	});

	const selectedRuns = $derived.by(() => {
		const list = Array.from(selected).map((id) => runs.find((run) => run.id === id) ?? null);
		return list.filter((run): run is EngineRun => run !== null);
	});

	const runA = $derived(selectedRuns[0] ?? null);
	const runB = $derived(selectedRuns[1] ?? null);
	const canCompare = $derived(selected.size === 2);

	const snapshots = $derived(snapshotsQuery.data ?? []);

	const runSnapshotMap = $derived.by(() => buildSnapshotMap(runs, snapshots));
	const snapshotA = $derived(runA ? (runSnapshotMap.get(runA.id) ?? null) : null);
	const snapshotB = $derived(runB ? (runSnapshotMap.get(runB.id) ?? null) : null);

	function toggleSelect(id: string) {
		if (selected.has(id)) {
			selected.delete(id);
			resetComparison();
			return;
		}
		if (selected.size >= 2) return;
		selected.add(id);
		resetComparison();
	}

	async function runComparison() {
		const snapA = snapshotA;
		const snapB = snapshotB;
		if (!snapA || !snapB) return;
		comparing = true;
		compareError = null;
		const result = await compareDatasourceSnapshots(datasource.id, snapA, snapB, rowLimit);
		if (result.isOk()) {
			comparison = result.value;
			comparing = false;
			return;
		}
		compareError = result.error.message;
		comparing = false;
	}

	function closeComparison() {
		selected.clear();
		resetComparison();
	}

	function resetComparison() {
		comparison = null;
		compareError = null;
	}

	function formatDate(isoDate: string): string {
		const date = new Date(isoDate);
		return date.toLocaleString();
	}

	function formatDelta(val: number): string {
		if (val === 0) return '0';
		const sign = val > 0 ? '+' : '';
		return `${sign}${val}`;
	}

	function rowDeltaClass(val: number): string {
		if (val === 0) return 'text-fg-muted';
		return val > 0 ? 'text-success-fg' : 'text-error-fg';
	}

	function nullDeltaClass(val: number): string {
		if (val === 0) return 'text-fg-muted';
		// More nulls (positive) -> bad (red/error)
		// Fewer nulls (negative) -> good (green/success)
		return val > 0 ? 'text-error-fg' : 'text-success-fg';
	}

	// Unique count logic: more unique is usually good (green), less is bad (red) or neutral
	// Matches rowDeltaClass logic
	function uniqueDeltaClass(val: number): string {
		if (val === 0) return 'text-fg-muted';
		return val > 0 ? 'text-success-fg' : 'text-error-fg';
	}

	function previewColumns(preview: SnapshotCompareResponse['preview_a'] | null) {
		return preview?.columns ?? [];
	}

	function previewData(preview: SnapshotCompareResponse['preview_a'] | null) {
		return preview?.data ?? [];
	}

	function previewTypes(preview: SnapshotCompareResponse['preview_a'] | null) {
		return preview?.column_types ?? {};
	}

	const combinedStats = $derived.by(() => {
		if (!comparison) return [];
		const statsA = new Map(comparison.stats_a.map((s) => [s.column, s]));
		const statsB = new Map(comparison.stats_b.map((s) => [s.column, s]));
		const allCols = new Set([...statsA.keys(), ...statsB.keys()]);
		return Array.from(allCols)
			.sort()
			.map((col) => {
				const a = statsA.get(col);
				const b = statsB.get(col);
				const nullA = a?.null_count;
				const nullB = b?.null_count;
				const uniqueA = a?.unique_count;
				const uniqueB = b?.unique_count;

				let nullDelta: number | null = null;
				if (typeof nullA === 'number' && typeof nullB === 'number') {
					nullDelta = nullB - nullA;
				}

				let uniqueDelta: number | null = null;
				if (typeof uniqueA === 'number' && typeof uniqueB === 'number') {
					uniqueDelta = uniqueB - uniqueA;
				}

				return {
					column: col,
					// Show A -> B if types differ, otherwise just Type
					type:
						a?.dtype === b?.dtype ? (a?.dtype ?? '-') : `${a?.dtype ?? '-'} → ${b?.dtype ?? '-'}`,
					null_a: nullA ?? '-',
					null_b: nullB ?? '-',
					null_delta: nullDelta,
					unique_a: uniqueA ?? '-',
					unique_b: uniqueB ?? '-',
					unique_delta: uniqueDelta,
					min_a: a?.min ?? '-',
					min_b: b?.min ?? '-',
					max_a: a?.max ?? '-',
					max_b: b?.max ?? '-'
				};
			});
	});
</script>

<div class="border border-tertiary bg-bg-primary flex flex-col min-h-0">
	<div class="flex items-center justify-between border-b border-tertiary bg-bg-tertiary px-4 py-3">
		<h3 class="m-0 flex items-center gap-2 text-sm font-medium">
			<GitCompareArrows size={16} class="text-accent-primary" />
			Build Comparison
		</h3>
		{#if comparison}
			<button class="btn-ghost btn-sm" onclick={closeComparison}>
				<X size={14} />
			</button>
		{/if}
	</div>

	{#if datasource.source_type !== 'iceberg'}
		<div class="p-4 text-sm text-fg-tertiary">
			Snapshot comparison is only available for Iceberg datasources.
		</div>
	{:else}
		<div class="flex-1 min-h-0 p-4 space-y-4 overflow-auto datasource-comparison-scroll">
			<div class="grid gap-3 md:grid-cols-2">
				<div class="border border-tertiary p-3">
					<div class="mb-2 text-xs font-medium text-fg-muted">Select builds</div>
					{#if runsQuery.isLoading}
						<div class="text-sm text-fg-tertiary">Loading runs...</div>
					{:else if runsQuery.isError}
						<div class="text-sm text-error-fg">
							{runsQuery.error instanceof Error ? runsQuery.error.message : 'Failed to load runs'}
						</div>
					{:else if runs.length === 0}
						<p class="text-sm text-fg-tertiary">No successful datasource builds recorded.</p>
					{:else}
						<div class="flex flex-col gap-3">
							<div class="relative">
								<Search
									size={12}
									class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted"
								/>
								<input
									type="text"
									placeholder="Search builds by ID or date..."
									class="w-full border border-tertiary bg-transparent px-3 py-1.5 pl-8 text-xs"
									bind:value={runSearch}
								/>
							</div>
							{#if visibleRuns.length === 0}
								<p class="text-xs text-fg-tertiary">No builds match your search.</p>
							{:else}
								<div class="max-h-72 space-y-2 overflow-y-auto datasource-comparison-scroll">
									{#each visibleRuns as run (run.id)}
										<button
											class="flex w-full items-start justify-between border border-tertiary bg-transparent px-3 py-2 text-left text-sm hover:bg-hover"
											class:bg-accent-bg={selected.has(run.id)}
											class:text-accent-primary={selected.has(run.id)}
											onclick={() => toggleSelect(run.id)}
										>
											<div class="min-w-0">
												<div class="flex items-center gap-2">
													<span class="font-mono text-xs">{run.id.slice(0, 8)}...</span>
													<span class="text-xs text-fg-tertiary">{run.kind}</span>
												</div>
												<div class="text-xs text-fg-muted">{formatDate(run.created_at)}</div>
											</div>
											<div class="text-xs text-fg-tertiary">
												{runSnapshotMap.get(run.id) ? 'snapshot mapped' : 'missing snapshot'}
											</div>
										</button>
									{/each}
								</div>
							{/if}
						</div>
					{/if}
				</div>
				<div class="border border-tertiary p-3">
					<div class="mb-2 text-xs font-medium text-fg-muted">Selected builds</div>
					<div class="space-y-2 text-sm">
						<div class="flex items-center gap-2">
							<GitCompareArrows size={14} class="text-fg-muted" />
							<span>{selected.size}/2 builds selected</span>
						</div>
						{#if selectedRuns.length === 0}
							<p class="text-xs text-fg-tertiary">Select two builds to compare.</p>
						{:else}
							<div class="space-y-2">
								{#each selectedRuns as run (run.id)}
									<div
										class="flex items-center justify-between border border-tertiary bg-bg-secondary px-3 py-2 text-xs"
									>
										<div class="flex items-center gap-2">
											<span class="font-mono">{run.id.slice(0, 8)}...</span>
											<span class="text-fg-tertiary">{run.kind}</span>
										</div>
										<button
											class="border-none bg-transparent text-fg-tertiary hover:text-fg-primary"
											onclick={() => toggleSelect(run.id)}
											title="Remove selection"
										>
											<X size={12} />
										</button>
									</div>
								{/each}
								{#if selectedRuns.length < 2}
									<p class="text-[10px] text-fg-tertiary">Select one more build.</p>
								{/if}
							</div>
							<button
								class="btn-primary btn-sm"
								disabled={!canCompare || comparing || !snapshotA || !snapshotB}
								onclick={runComparison}
							>
								{#if comparing}
									<RefreshCw size={13} class="animate-spin" />
								{/if}
								Compare snapshots
							</button>
							{#if compareError}
								<div class="text-xs text-error-fg">{compareError}</div>
							{/if}
							{#if !snapshotA || !snapshotB}
								<div class="text-xs text-warning-fg">
									Snapshot mapping missing for one or both builds.
								</div>
							{/if}
						{/if}
					</div>
				</div>
			</div>

			{#if comparison}
				<div class="border border-tertiary">
					<div class="grid gap-4 border-b border-tertiary p-4 md:grid-cols-3">
						<div class="border border-tertiary p-3 text-center">
							<div class="text-xs text-fg-muted">Row Count A</div>
							<div class="mt-1 font-mono text-lg">{comparison.row_count_a}</div>
						</div>
						<div class="border border-tertiary p-3 text-center">
							<div class="text-xs text-fg-muted">Row Count B</div>
							<div class="mt-1 font-mono text-lg">{comparison.row_count_b}</div>
						</div>
						<div class="border border-tertiary p-3 text-center">
							<div class="text-xs text-fg-muted">Row Count Delta</div>
							<div class={`mt-1 font-mono text-lg ${rowDeltaClass(comparison.row_count_delta)}`}>
								{formatDelta(comparison.row_count_delta)}
							</div>
						</div>
					</div>
					<div class="p-4">
						<h4 class="mb-2 text-sm font-medium text-fg-secondary">Schema Changes</h4>
						{#if comparison.schema_diff.length > 0}
							<div class="border border-tertiary">
								<table class="w-full border-collapse text-sm">
									<thead>
										<tr class="bg-bg-tertiary">
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Column</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Change</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Type A</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Type B</th
											>
										</tr>
									</thead>
									<tbody>
										{#each comparison.schema_diff as diff (diff.column)}
											<tr>
												<td class="border-b border-tertiary px-3 py-1.5 font-mono text-xs"
													>{diff.column}</td
												>
												<td class="border-b border-tertiary px-3 py-1.5">
													{#if diff.status === 'added'}
														<span class="inline-flex items-center gap-1 text-xs text-success-fg">
															<Plus size={12} /> Added
														</span>
													{:else if diff.status === 'removed'}
														<span class="inline-flex items-center gap-1 text-xs text-error-fg">
															<Minus size={12} /> Removed
														</span>
													{:else}
														<span class="inline-flex items-center gap-1 text-xs text-warning-fg">
															<RefreshCw size={12} /> Changed
														</span>
													{/if}
												</td>
												<td
													class="border-b border-tertiary px-3 py-1.5 font-mono text-xs text-fg-muted"
												>
													{diff.type_a ?? '-'}
												</td>
												<td
													class="border-b border-tertiary px-3 py-1.5 font-mono text-xs text-fg-muted"
												>
													{diff.type_b ?? '-'}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{:else}
							<div
								class="border border-tertiary bg-bg-tertiary p-4 text-center text-sm text-fg-tertiary"
							>
								No schema changes detected
							</div>
						{/if}
					</div>

					<div class="p-4">
						<h4 class="mb-2 text-sm font-medium text-fg-secondary">Column Statistics</h4>
						<div class="border border-tertiary">
							<div class="max-h-[500px] overflow-auto datasource-comparison-scroll">
								<table class="w-full border-collapse text-sm">
									<thead class="sticky top-0 z-10 bg-bg-tertiary shadow-sm">
										<tr>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Column</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Type</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Null Count (A → B)</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Unique Count (A → B)</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Min (A → B)</th
											>
											<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium"
												>Max (A → B)</th
											>
										</tr>
									</thead>
									<tbody>
										{#each combinedStats as stat (stat.column)}
											<tr>
												<td
													class="border-b border-tertiary px-3 py-1.5 font-mono text-xs font-medium"
												>
													{stat.column}
												</td>
												<td
													class="border-b border-tertiary px-3 py-1.5 font-mono text-xs text-fg-muted"
												>
													{stat.type}
												</td>
												<td class="border-b border-tertiary px-3 py-1.5 font-mono text-xs">
													<div class="flex items-baseline gap-2">
														<span class="text-fg-muted">{stat.null_a}</span>
														<span class="text-fg-tertiary">→</span>
														<span>{stat.null_b}</span>
														{#if stat.null_delta !== null}
															<span class="ml-1 text-[10px] {nullDeltaClass(stat.null_delta)}">
																({formatDelta(stat.null_delta)})
															</span>
														{/if}
													</div>
												</td>
												<td class="border-b border-tertiary px-3 py-1.5 font-mono text-xs">
													<div class="flex items-baseline gap-2">
														<span class="text-fg-muted">{stat.unique_a}</span>
														<span class="text-fg-tertiary">→</span>
														<span>{stat.unique_b}</span>
														{#if stat.unique_delta !== null}
															<span class="ml-1 text-[10px] {uniqueDeltaClass(stat.unique_delta)}">
																({formatDelta(stat.unique_delta)})
															</span>
														{/if}
													</div>
												</td>
												<td
													class="border-b border-tertiary px-3 py-1.5 font-mono text-xs text-fg-muted"
												>
													{#if stat.min_a === stat.min_b}
														{stat.min_b}
													{:else}
														<span class="text-fg-tertiary">{stat.min_a}</span>
														<span class="mx-1">→</span>
														<span>{stat.min_b}</span>
													{/if}
												</td>
												<td
													class="border-b border-tertiary px-3 py-1.5 font-mono text-xs text-fg-muted"
												>
													{#if stat.max_a === stat.max_b}
														{stat.max_b}
													{:else}
														<span class="text-fg-tertiary">{stat.max_a}</span>
														<span class="mx-1">→</span>
														<span>{stat.max_b}</span>
													{/if}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						</div>
					</div>
					<div class="grid gap-4 p-4 md:grid-cols-2">
						<div class="border border-tertiary">
							<div
								class="border-b border-tertiary bg-bg-tertiary px-3 py-2 text-xs font-medium text-fg-muted"
							>
								Snapshot A preview
							</div>
							<div class="h-80 datasource-comparison-scroll">
								<DataTable
									columns={previewColumns(comparison.preview_a)}
									data={previewData(comparison.preview_a)}
									columnTypes={previewTypes(comparison.preview_a)}
									fillContainer
									showHeader
								/>
							</div>
						</div>
						<div class="border border-tertiary">
							<div
								class="border-b border-tertiary bg-bg-tertiary px-3 py-2 text-xs font-medium text-fg-muted"
							>
								Snapshot B preview
							</div>
							<div class="h-80 datasource-comparison-scroll">
								<DataTable
									columns={previewColumns(comparison.preview_b)}
									data={previewData(comparison.preview_b)}
									columnTypes={previewTypes(comparison.preview_b)}
									fillContainer
									showHeader
								/>
							</div>
						</div>
					</div>
				</div>
			{:else if selected.size > 0}
				<div class="border border-tertiary p-4 text-sm text-fg-tertiary">
					Select two builds to enable snapshot comparison.
				</div>
			{/if}
		</div>
	{/if}
</div>
