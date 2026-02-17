<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { listEngineRuns, compareEngineRuns } from '$lib/api/engine-runs';
	import type { BuildComparison, EngineRun } from '$lib/api/engine-runs';
	import type { DataSource } from '$lib/types/datasource';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import { buildDatasourcePipelinePayload } from '$lib/utils/analysis-pipeline';
	import DataTable from '$lib/components/viewers/DataTable.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import type { Schema } from '$lib/types/schema';
	import { GitCompareArrows, RefreshCw, X, Plus, Minus, ArrowRightLeft } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';

	interface Props {
		datasource: DataSource;
	}

	let { datasource }: Props = $props();

	const selected = new SvelteSet<string>();
	let comparison = $state<BuildComparison | null>(null);
	let comparing = $state(false);
	let compareError = $state<string | null>(null);
	let mapping = $state<Record<string, string>>({});

	let pageA = $state(1);
	let pageB = $state(1);
	let rowLimit = $state(50);

	const runsQuery = createQuery(() => ({
		queryKey: ['engine-runs', datasource.id],
		queryFn: async () => {
			const result = await listEngineRuns({ datasource_id: datasource.id, limit: 50 });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const runs = $derived((runsQuery.data ?? []).filter((run) => run.kind !== 'datasource_create'));
	const selectedRuns = $derived.by(() => {
		const list = Array.from(selected).map((id) => runs.find((run) => run.id === id) ?? null);
		return list.filter((run): run is EngineRun => run !== null);
	});
	const runA = $derived(selectedRuns[0] ?? null);
	const runB = $derived(selectedRuns[1] ?? null);
	const canCompare = $derived(selected.size === 2);

	const schemaA = $derived(buildSchema(runA));
	const schemaB = $derived(buildSchema(runB));

	const defaultMapping = $derived.by(() => {
		if (!schemaA || !schemaB) return {};
		const next: Record<string, string> = {};
		for (const col of schemaA.columns) {
			if (schemaB.columns.some((right) => right.name === col.name)) {
				next[col.name] = col.name;
			}
		}
		return next;
	});

	const effectiveMapping = $derived.by(() => {
		const next = { ...defaultMapping };
		for (const [left, right] of Object.entries(mapping)) {
			if (!right) {
				delete next[left];
				continue;
			}
			next[left] = right;
		}
		return next;
	});

	const mappingEntries = $derived.by(() => {
		if (!schemaA || !schemaB) return [];
		const entries: Array<{ left: string; right: string | null }> = [];
		for (const col of schemaA.columns) {
			entries.push({ left: col.name, right: effectiveMapping[col.name] ?? null });
		}
		return entries;
	});

	const diffColumns = $derived.by(() => mappingEntries.filter((entry) => entry.right));

	const previewKeyA = $derived.by(() => buildPreviewKey(runA));
	const previewKeyB = $derived.by(() => buildPreviewKey(runB));

	const previewQueryA = createQuery(() => ({
		queryKey: ['datasource-run-preview', previewKeyA, pageA, rowLimit],
		queryFn: () => fetchPreview(runA, pageA, rowLimit),
		enabled: !!previewKeyA
	}));
	const previewQueryB = createQuery(() => ({
		queryKey: ['datasource-run-preview', previewKeyB, pageB, rowLimit],
		queryFn: () => fetchPreview(runB, pageB, rowLimit),
		enabled: !!previewKeyB
	}));

	const dataA = $derived(previewQueryA.data ?? null);
	const dataB = $derived(previewQueryB.data ?? null);

	const diffColumnTypes = $derived.by(() => buildDiffColumnTypes(schemaA, schemaB, diffColumns));
	const diffColumnNames = $derived.by(() => diffColumnTypes.map((col) => col.name));
	const diffRows = $derived.by(() =>
		buildDiffRows(dataA?.data ?? [], dataB?.data ?? [], diffColumns)
	);

	function buildSchema(run: EngineRun | null): Schema | null {
		if (!run?.result_json) return null;
		const schemaData = run.result_json.schema;
		if (!schemaData || typeof schemaData !== 'object' || Array.isArray(schemaData)) return null;
		const columns = Object.entries(schemaData as Record<string, string>).map(([name, dtype]) => ({
			name,
			dtype,
			nullable: true
		}));
		return { columns, row_count: null };
	}

	function buildRunConfig(run: EngineRun): Record<string, unknown> | null {
		const base = datasource.config ?? {};
		const runConfig = run.request_json?.datasource_config;
		const runOverrides =
			runConfig && typeof runConfig === 'object' ? (runConfig as Record<string, unknown>) : null;
		const merged = { ...base, ...(runOverrides ?? {}) } as Record<string, unknown>;
		if (datasource.source_type !== 'iceberg') return merged;
		if (merged.snapshot_id) return merged;
		if (merged.snapshot_timestamp_ms) return merged;
		const runTime = Date.parse(run.created_at);
		if (Number.isNaN(runTime)) return merged;
		return { ...merged, snapshot_timestamp_ms: runTime };
	}

	function buildPreviewKey(run: EngineRun | null): string | null {
		if (!run) return null;
		const config = buildRunConfig(run);
		const snapshotId = config?.snapshot_id ?? null;
		const snapshotTs = config?.snapshot_timestamp_ms ?? null;
		return JSON.stringify({ run: run.id, snapshotId, snapshotTs });
	}

	function buildPreviewRequest(run: EngineRun, page: number, limit: number) {
		const configData = buildRunConfig(run);
		if (!configData) return null;
		const pipeline = buildDatasourcePipelinePayload({
			datasource,
			datasourceConfig: configData
		});
		return {
			analysis_id: datasource.id,
			target_step_id: 'source',
			analysis_pipeline: pipeline,
			row_limit: limit,
			page,
			datasource_config: configData
		};
	}

	async function fetchPreview(
		run: EngineRun | null,
		page: number,
		limit: number
	): Promise<StepPreviewResponse> {
		if (!run) {
			return { step_id: 'source', columns: [], data: [], total_rows: 0, page, page_size: 0 };
		}
		const request = buildPreviewRequest(run, page, limit);
		if (!request) {
			return { step_id: 'source', columns: [], data: [], total_rows: 0, page, page_size: 0 };
		}
		const result = await previewStepData(request);
		if (result.isErr()) {
			throw new Error(result.error.message);
		}
		return result.value;
	}

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
		const ids = [...selected];
		if (ids.length !== 2) return;
		comparing = true;
		compareError = null;
		const result = await compareEngineRuns(ids[0], ids[1]);
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
		mapping = {};
		pageA = 1;
		pageB = 1;
	}

	function formatDuration(ms: number | null): string {
		if (ms === null) return '-';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(2)}s`;
	}

	function formatDate(isoDate: string): string {
		const date = new Date(isoDate);
		return date.toLocaleString();
	}

	function formatDelta(val: number | null): string {
		if (val === null) return '-';
		const sign = val > 0 ? '+' : '';
		return `${sign}${val}`;
	}

	function formatDeltaPct(val: number | null): string {
		if (val === null) return '';
		const sign = val > 0 ? '+' : '';
		return `(${sign}${val}%)`;
	}

	function deltaClass(val: number | null): string {
		if (val === null || val === 0) return 'text-fg-muted';
		return val > 0 ? 'text-error-fg' : 'text-success-fg';
	}

	function rowDeltaClass(val: number | null): string {
		if (val === null || val === 0) return 'text-fg-muted';
		return val > 0 ? 'text-success-fg' : 'text-error-fg';
	}

	function updateMapping(left: string, right: string) {
		if (!right) {
			const { [left]: _, ...rest } = mapping;
			mapping = rest;
			return;
		}
		mapping = { ...mapping, [left]: right };
	}

	function buildDiffColumnTypes(
		left: Schema | null,
		right: Schema | null,
		pairs: Array<{ left: string; right: string | null }>
	) {
		const columns = [] as Array<{ name: string; type: string }>;
		if (!left || !right) return columns;
		for (const pair of pairs) {
			if (!pair.right) continue;
			const leftCol = left.columns.find((col) => col.name === pair.left) ?? null;
			const rightCol = right.columns.find((col) => col.name === pair.right) ?? null;
			columns.push({
				name: `${pair.left} → ${pair.right}`,
				type: 'string'
			});
			columns.push({
				name: `${pair.left} Δ`,
				type: leftCol?.dtype ?? rightCol?.dtype ?? '-'
			});
		}
		return columns;
	}

	function buildDiffRows(
		leftRows: Array<Record<string, unknown>>,
		rightRows: Array<Record<string, unknown>>,
		pairs: Array<{ left: string; right: string | null }>
	) {
		const rows = [] as Array<Record<string, unknown>>;
		const maxRows = Math.max(leftRows.length, rightRows.length);
		for (let idx = 0; idx < maxRows; idx += 1) {
			const left = leftRows[idx] ?? {};
			const right = rightRows[idx] ?? {};
			const row: Record<string, unknown> = { _row: idx + 1 };
			for (const pair of pairs) {
				if (!pair.right) continue;
				const leftValue = left[pair.left] ?? null;
				const rightValue = right[pair.right] ?? null;
				const leftText = leftValue === null || leftValue === undefined ? '-' : String(leftValue);
				const rightText =
					rightValue === null || rightValue === undefined ? '-' : String(rightValue);
				row[`${pair.left} → ${pair.right}`] = `${leftText} | ${rightText}`;
				row[`${pair.left} Δ`] = leftValue === rightValue ? 'match' : 'diff';
			}
			rows.push(row);
		}
		return rows;
	}

	function canPrev(page: number) {
		return page > 1;
	}

	function canNext(pageSize: number) {
		return pageSize === rowLimit;
	}
</script>

<div class="border border-tertiary bg-bg-primary">
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

	<div class="p-4 space-y-4">
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
					<p class="text-sm text-fg-tertiary">No builds recorded for this datasource.</p>
				{:else}
					<div class="space-y-2">
						{#each runs as run (run.id)}
							<button
								class="flex w-full items-center justify-between border border-tertiary bg-transparent px-3 py-2 text-left text-sm hover:bg-hover"
								class:bg-accent-bg={selected.has(run.id)}
								class:text-accent-primary={selected.has(run.id)}
								onclick={() => toggleSelect(run.id)}
							>
								<div>
									<div class="flex items-center gap-2">
										<span class="font-mono text-xs">{run.id.slice(0, 8)}...</span>
										<span class="text-xs text-fg-tertiary">{run.kind}</span>
									</div>
									<div class="text-xs text-fg-muted">{formatDate(run.created_at)}</div>
								</div>
								<div class="text-xs text-fg-tertiary">
									{run.status}
								</div>
							</button>
						{/each}
					</div>
				{/if}
			</div>
			<div class="border border-tertiary p-3">
				<div class="mb-2 text-xs font-medium text-fg-muted">Comparison</div>
				<div class="space-y-2 text-sm">
					<div class="flex items-center gap-2">
						<GitCompareArrows size={14} class="text-fg-muted" />
						<span>{selected.size}/2 builds selected</span>
					</div>
					<button
						class="btn-primary btn-sm"
						disabled={!canCompare || comparing}
						onclick={runComparison}
					>
						{#if comparing}
							<RefreshCw size={13} class="animate-spin" />
						{/if}
						Compare metadata
					</button>
					{#if compareError}
						<div class="text-xs text-error-fg">{compareError}</div>
					{/if}
					{#if comparison}
						<div class="text-xs text-fg-tertiary">Selected build comparison ready.</div>
					{/if}
				</div>
			</div>
		</div>

		{#if comparison}
			<div class="border border-tertiary">
				<div class="grid gap-4 p-4 md:grid-cols-2">
					<div class="border border-tertiary p-3">
						<div class="mb-2 text-xs font-medium text-fg-muted">Run A</div>
						<div class="space-y-1 text-sm">
							<div>
								<span class="text-fg-muted">ID:</span>
								<span class="font-mono text-xs">{comparison.run_a.id.slice(0, 8)}...</span>
							</div>
							<div><span class="text-fg-muted">Type:</span> {comparison.run_a.kind}</div>
							<div><span class="text-fg-muted">Status:</span> {comparison.run_a.status}</div>
							<div>
								<span class="text-fg-muted">Duration:</span>
								{formatDuration(comparison.run_a.duration_ms)}
							</div>
							<div><span class="text-fg-muted">Rows:</span> {comparison.row_count_a ?? '-'}</div>
							<div>
								<span class="text-fg-muted">Created:</span>
								{formatDate(comparison.run_a.created_at)}
							</div>
						</div>
					</div>
					<div class="border border-tertiary p-3">
						<div class="mb-2 text-xs font-medium text-fg-muted">Run B</div>
						<div class="space-y-1 text-sm">
							<div>
								<span class="text-fg-muted">ID:</span>
								<span class="font-mono text-xs">{comparison.run_b.id.slice(0, 8)}...</span>
							</div>
							<div><span class="text-fg-muted">Type:</span> {comparison.run_b.kind}</div>
							<div><span class="text-fg-muted">Status:</span> {comparison.run_b.status}</div>
							<div>
								<span class="text-fg-muted">Duration:</span>
								{formatDuration(comparison.run_b.duration_ms)}
							</div>
							<div><span class="text-fg-muted">Rows:</span> {comparison.row_count_b ?? '-'}</div>
							<div>
								<span class="text-fg-muted">Created:</span>
								{formatDate(comparison.run_b.created_at)}
							</div>
						</div>
					</div>
				</div>
				<div class="grid gap-4 border-t border-tertiary p-4 md:grid-cols-3">
					<div class="border border-tertiary p-3 text-center">
						<div class="text-xs text-fg-muted">Row Count Delta</div>
						<div class={`mt-1 font-mono text-lg ${rowDeltaClass(comparison.row_count_delta)}`}>
							{formatDelta(comparison.row_count_delta)}
						</div>
					</div>
					<div class="border border-tertiary p-3 text-center">
						<div class="text-xs text-fg-muted">Duration Delta</div>
						<div class={`mt-1 font-mono text-lg ${deltaClass(comparison.total_duration_delta_ms)}`}>
							{comparison.total_duration_delta_ms !== null
								? formatDuration(Math.abs(comparison.total_duration_delta_ms))
								: '-'}
							{#if comparison.total_duration_delta_ms !== null}
								<span class="text-xs"
									>{comparison.total_duration_delta_ms > 0 ? 'slower' : 'faster'}</span
								>
							{/if}
						</div>
					</div>
					<div class="border border-tertiary p-3 text-center">
						<div class="text-xs text-fg-muted">Schema Changes</div>
						<div
							class={`mt-1 font-mono text-lg ${
								comparison.schema_diff.length > 0 ? 'text-warning-fg' : 'text-fg-muted'
							}`}
						>
							{comparison.schema_diff.length}
						</div>
					</div>
				</div>
				{#if comparison.schema_diff.length > 0}
					<div class="p-4">
						<h4 class="mb-2 text-sm font-medium text-fg-secondary">Schema Changes</h4>
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
					</div>
				{/if}
				{#if comparison.timing_diff.length > 0}
					<div class="p-4">
						<h4 class="mb-2 text-sm font-medium text-fg-secondary">Step Timing Comparison</h4>
						<div class="border border-tertiary">
							<table class="w-full border-collapse text-sm">
								<thead>
									<tr class="bg-bg-tertiary">
										<th class="border-b border-tertiary px-3 py-1.5 text-left font-medium">Step</th>
										<th class="border-b border-tertiary px-3 py-1.5 text-right font-medium"
											>Run A</th
										>
										<th class="border-b border-tertiary px-3 py-1.5 text-right font-medium"
											>Run B</th
										>
										<th class="border-b border-tertiary px-3 py-1.5 text-right font-medium"
											>Delta</th
										>
									</tr>
								</thead>
								<tbody>
									{#each comparison.timing_diff as diff (diff.step)}
										<tr>
											<td
												class="border-b border-tertiary px-3 py-1.5 font-mono text-xs"
												title={diff.step}
											>
												{diff.step.length > 30 ? diff.step.slice(0, 30) + '...' : diff.step}
											</td>
											<td
												class="border-b border-tertiary px-3 py-1.5 text-right font-mono text-xs text-fg-muted"
											>
												{diff.ms_a !== null ? formatDuration(diff.ms_a) : '-'}
											</td>
											<td
												class="border-b border-tertiary px-3 py-1.5 text-right font-mono text-xs text-fg-muted"
											>
												{diff.ms_b !== null ? formatDuration(diff.ms_b) : '-'}
											</td>
											<td
												class={`border-b border-tertiary px-3 py-1.5 text-right font-mono text-xs ${deltaClass(
													diff.delta_ms
												)}`}
											>
												{diff.delta_ms !== null ? formatDuration(Math.abs(diff.delta_ms)) : '-'}
												{#if diff.delta_ms !== null}
													<span class="text-fg-muted"
														>{diff.delta_ms > 0 ? 'slower' : 'faster'}</span
													>
												{/if}
												{#if diff.delta_pct !== null}
													<span class="ml-1 text-fg-muted">{formatDeltaPct(diff.delta_pct)}</span>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}
			</div>
		{/if}

		{#if runA && runB}
			<div class="border border-tertiary">
				<div
					class="flex items-center justify-between border-b border-tertiary bg-bg-tertiary px-4 py-2"
				>
					<div class="flex items-center gap-2 text-xs uppercase tracking-wide text-fg-muted">
						<ArrowRightLeft size={12} /> Column mapping + dataset diff
					</div>
					<div class="text-xs text-fg-tertiary">
						{runA.id.slice(0, 8)} ↔ {runB.id.slice(0, 8)}
					</div>
				</div>
				<div class="grid gap-4 p-4 md:grid-cols-2">
					<div class="border border-tertiary p-3">
						<div class="mb-2 text-xs font-medium text-fg-muted">Run A schema</div>
						{#if schemaA}
							<div class="space-y-2 datasource-comparison-scroll max-h-80 overflow-y-auto">
								{#each schemaA.columns as col (col.name)}
									<div class="grid grid-cols-[1fr,1fr] gap-2 items-center">
										<div class="text-xs font-mono text-fg-secondary">{col.name}</div>
										{#if schemaB}
											<ColumnDropdown
												schema={schemaB}
												value={mapping[col.name] ?? ''}
												onChange={(val) => updateMapping(col.name, val)}
												placeholder="Map to column..."
											/>
										{:else}
											<div class="text-xs text-fg-tertiary">No target schema</div>
										{/if}
									</div>
								{/each}
							</div>
						{:else}
							<p class="text-sm text-fg-tertiary">No schema captured for run A.</p>
						{/if}
					</div>
					<div class="border border-tertiary p-3">
						<div class="mb-2 text-xs font-medium text-fg-muted">Run B schema</div>
						{#if schemaB}
							<div
								class="space-y-1 text-xs text-fg-secondary datasource-comparison-scroll max-h-80 overflow-y-auto"
							>
								{#each schemaB.columns as col (col.name)}
									<div class="flex items-center justify-between border-b border-tertiary py-1">
										<span class="font-mono">{col.name}</span>
										<span class="text-fg-muted">{col.dtype}</span>
									</div>
								{/each}
							</div>
						{:else}
							<p class="text-sm text-fg-tertiary">No schema captured for run B.</p>
						{/if}
					</div>
				</div>
				<div class="grid gap-4 p-4 md:grid-cols-2">
					<div class="border border-tertiary">
						<div
							class="border-b border-tertiary bg-bg-tertiary px-3 py-2 text-xs font-medium text-fg-muted"
						>
							Run A data
						</div>
						<div class="h-80 datasource-comparison-scroll">
							<DataTable
								columns={dataA?.columns ?? []}
								data={dataA?.data ?? []}
								columnTypes={dataA?.column_types ?? {}}
								loading={previewQueryA.isLoading}
								error={previewQueryA.error as Error | null}
								fillContainer
								showHeader
								showPagination
								pagination={{
									page: pageA,
									canPrev: canPrev(pageA),
									canNext: canNext(dataA?.data?.length ?? 0),
									onPrev: () => (pageA -= 1),
									onNext: () => (pageA += 1)
								}}
							/>
						</div>
					</div>
					<div class="border border-tertiary">
						<div
							class="border-b border-tertiary bg-bg-tertiary px-3 py-2 text-xs font-medium text-fg-muted"
						>
							Run B data
						</div>
						<div class="h-80 datasource-comparison-scroll">
							<DataTable
								columns={dataB?.columns ?? []}
								data={dataB?.data ?? []}
								columnTypes={dataB?.column_types ?? {}}
								loading={previewQueryB.isLoading}
								error={previewQueryB.error as Error | null}
								fillContainer
								showHeader
								showPagination
								pagination={{
									page: pageB,
									canPrev: canPrev(pageB),
									canNext: canNext(dataB?.data?.length ?? 0),
									onPrev: () => (pageB -= 1),
									onNext: () => (pageB += 1)
								}}
							/>
						</div>
					</div>
				</div>
				<div class="p-4">
					<div class="border border-tertiary">
						<div
							class="border-b border-tertiary bg-bg-tertiary px-3 py-2 text-xs font-medium text-fg-muted"
						>
							Row-level diff (mapped columns)
						</div>
						<div class="h-80 datasource-comparison-scroll">
							<DataTable
								columns={['_row', ...diffColumnNames]}
								data={diffRows}
								columnTypes={Object.fromEntries(diffColumnTypes.map((col) => [col.name, col.type]))}
								fillContainer
								showHeader
								showPagination
								pagination={{
									page: 1,
									canPrev: false,
									canNext: false,
									onPrev: () => {},
									onNext: () => {}
								}}
							/>
						</div>
					</div>
				</div>
			</div>
		{:else if selected.size > 0}
			<div class="border border-tertiary p-4 text-sm text-fg-tertiary">
				Select two builds to enable dataset comparison.
			</div>
		{/if}
	</div>
</div>
