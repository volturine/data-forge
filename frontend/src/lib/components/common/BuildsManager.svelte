<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { listEngineRuns, type EngineRun, type ListEngineRunsParams } from '$lib/api/engine-runs';
	import { listDatasources } from '$lib/api/datasource';
	import { listAnalyses } from '$lib/api/analysis';
	import { page as pageState } from '$app/state';
	import {
		Search,
		CircleCheck,
		CircleX,
		Eye,
		EyeOff,
		Download,
		ChevronLeft,
		ChevronRight,
		ChevronDown,
		ArrowUp,
		ArrowDown,
		Timer,
		CalendarClock,
		Database,
		RefreshCw
	} from 'lucide-svelte';
	import BranchPicker from '$lib/components/common/BranchPicker.svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';

	interface Props {
		compact?: boolean;
		searchQuery?: string;
		showPreviews?: boolean;
	}

	let { compact = false, searchQuery, showPreviews = false }: Props = $props();

	let search = $state('');
	const effectiveSearch = $derived(searchQuery ?? search);
	let kindFilter = $state<string>('');
	let statusFilter = $state<'success' | 'failed' | ''>('');
	let dateFrom = $state('');
	let dateTo = $state('');
	let page = $state(1);
	let branchFilter = $state('master');
	let expandedId = $state<string | null>(null);
	let activeTab = $state<'request' | 'result' | 'plans' | 'timings'>('request');
	let sortColumn = $state<string>('created_at');
	let sortDir = $state<'asc' | 'desc'>('desc');
	const limit = 50;
	const previewsVisible = $derived(showPreviews);

	const params = $derived({
		analysis_id: (pageState.url.searchParams.get('analysis_id') ?? undefined) || undefined,
		datasource_id: (pageState.url.searchParams.get('datasource_id') ?? undefined) || undefined,
		kind: kindFilter || undefined,
		status: statusFilter || undefined,
		limit,
		offset: (page - 1) * limit
	});

	const query = createQuery(() => ({
		queryKey: ['engine-runs', params],
		queryFn: async () => {
			const result = await listEngineRuns(params as ListEngineRunsParams);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) return [];
			return result.value;
		},
		staleTime: 60_000
	}));

	const analysesQuery = createQuery(() => ({
		queryKey: ['analyses-lookup'],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) return [];
			return result.value;
		},
		staleTime: 60_000
	}));

	const dsNames = $derived.by(() => {
		const map = new SvelteMap<string, string>();
		for (const ds of datasourcesQuery.data ?? []) {
			map.set(ds.id, ds.name);
		}
		return map;
	});

	const analysisNames = $derived.by(() => {
		const map = new SvelteMap<string, string>();
		for (const a of analysesQuery.data ?? []) {
			map.set(a.id, a.name);
		}
		return map;
	});

	const runs = $derived(query.data ?? []);

	const filteredRuns = $derived.by(() => {
		let result = runs;

		if (!previewsVisible) {
			result = result.filter((run) => run.kind !== 'preview');
		}

		if (effectiveSearch) {
			const q = effectiveSearch.toLowerCase();
			result = result.filter(
				(r) =>
					r.id.toLowerCase().includes(q) ||
					r.datasource_id.toLowerCase().includes(q) ||
					(r.analysis_id && r.analysis_id.toLowerCase().includes(q)) ||
					(dsNames.get(r.datasource_id) ?? '').toLowerCase().includes(q) ||
					(r.analysis_id && (analysisNames.get(r.analysis_id) ?? '').toLowerCase().includes(q))
			);
		}

		if (dateFrom) {
			const from = new Date(dateFrom);
			result = result.filter((r) => new Date(r.created_at) >= from);
		}
		if (dateTo) {
			// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local Date for comparison, not reactive state
			const to = new Date(dateTo);
			to.setHours(23, 59, 59, 999);
			result = result.filter((r) => new Date(r.created_at) <= to);
		}

		if (branchFilter) {
			result = result.filter((run) => {
				const payload = run.request_json as Record<string, unknown>;
				const opts = payload.iceberg_options as Record<string, unknown> | undefined;
				const runBranch = opts?.branch as string | undefined;
				return runBranch === branchFilter;
			});
		}

		return sortRuns(result);
	});

	const branchOptions = $derived.by(() => {
		const set = new SvelteSet<string>();
		set.add('master');
		for (const run of runs) {
			const payload = run.request_json as Record<string, unknown>;
			const opts = payload.iceberg_options as Record<string, unknown> | undefined;
			const runBranch = opts?.branch as string | undefined;
			if (runBranch) set.add(runBranch);
		}
		return Array.from(set).sort((a, b) => a.localeCompare(b));
	});

	function sortRuns(list: EngineRun[]): EngineRun[] {
		const dir = sortDir === 'asc' ? 1 : -1;
		return [...list].sort((a, b) => {
			if (sortColumn === 'created_at') {
				return dir * (new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
			}
			if (sortColumn === 'duration_ms') {
				return dir * ((a.duration_ms ?? 0) - (b.duration_ms ?? 0));
			}
			if (sortColumn === 'kind') {
				return dir * a.kind.localeCompare(b.kind);
			}
			if (sortColumn === 'status') {
				return dir * a.status.localeCompare(b.status);
			}
			if (sortColumn === 'datasource') {
				const an = dsNames.get(a.datasource_id) ?? a.datasource_id;
				const bn = dsNames.get(b.datasource_id) ?? b.datasource_id;
				return dir * an.localeCompare(bn);
			}
			if (sortColumn === 'analysis') {
				const an = a.analysis_id ? (analysisNames.get(a.analysis_id) ?? a.analysis_id) : '';
				const bn = b.analysis_id ? (analysisNames.get(b.analysis_id) ?? b.analysis_id) : '';
				return dir * an.localeCompare(bn);
			}
			if (sortColumn === 'output') {
				const an = getOutputName(a) ?? '';
				const bn = getOutputName(b) ?? '';
				return dir * an.localeCompare(bn);
			}
			return 0;
		});
	}

	function toggleSort(col: string) {
		if (sortColumn === col) {
			sortDir = sortDir === 'asc' ? 'desc' : 'asc';
			return;
		}
		sortColumn = col;
		sortDir = col === 'created_at' || col === 'duration_ms' ? 'desc' : 'asc';
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

	function prevPage() {
		if (page > 1) page--;
	}

	function nextPage() {
		if (filteredRuns.length >= limit) page++;
	}

	function toggleExpand(id: string) {
		if (expandedId === id) {
			expandedId = null;
			return;
		}
		expandedId = id;
		activeTab = 'request';
	}

	function getQueryPlans(run: EngineRun): { optimized: string; unoptimized: string } | null {
		const result = run.result_json;
		if (result && typeof result === 'object') {
			const plans = result.query_plans as { optimized?: string; unoptimized?: string } | undefined;
			if (plans) {
				return {
					optimized: plans.optimized ?? '',
					unoptimized: plans.unoptimized ?? ''
				};
			}
		}
		if (!run.query_plan) return null;
		return {
			optimized: run.query_plan,
			unoptimized: run.query_plan
		};
	}

	function hasPlans(run: EngineRun): boolean {
		return getQueryPlans(run) !== null;
	}

	function hasTimings(run: EngineRun): boolean {
		return Object.keys(run.step_timings ?? {}).length > 0;
	}

	function getTimingEntries(run: EngineRun): { name: string; ms: number; pct: number }[] {
		const timings = run.step_timings ?? {};
		const entries = Object.entries(timings).map(([name, ms]) => ({
			name,
			ms: ms as number
		}));
		const total = entries.reduce((sum, e) => sum + e.ms, 0);
		if (total === 0) return entries.map((e) => ({ ...e, pct: 0 }));
		return entries.map((e) => ({ ...e, pct: (e.ms / total) * 100 }));
	}

	function resolveName(id: string, map: Map<string, string>): string {
		return map.get(id) ?? id.slice(0, 8) + '...';
	}

	function getOutputName(run: EngineRun): string | null {
		if (!run.result_json) return null;
		const name = run.result_json.datasource_name;
		if (typeof name === 'string') return name;
		return null;
	}
</script>

<div class="builds-page flex flex-col h-full w-full">
	{#if !compact}
		<header class="mb-6 border-b border-tertiary pb-5">
			<h1 class="m-0 mb-2 text-2xl">Builds</h1>
			<p class="m-0 text-fg-tertiary">Engine run history for previews and exports</p>
		</header>
	{/if}

	{#if compact}
		{#if searchQuery === undefined}
			<div class="mb-3 flex items-center gap-2">
				<div class="relative min-w-60 flex-1">
					<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
					<input
						type="text"
						placeholder="Search builds..."
						class="w-full border border-tertiary bg-transparent px-3 py-1.5 pl-8 text-sm"
						bind:value={search}
					/>
				</div>
			</div>
			<button
				class="btn-ghost btn-sm border border-tertiary text-xs w-fit"
				onclick={() => (showPreviews = !showPreviews)}
				aria-pressed={showPreviews}
			>
				{#if showPreviews}
					<Eye size={12} />
					Hide previews
				{:else}
					<EyeOff size={12} />
					Show previews
				{/if}
			</button>
		{/if}
	{:else}
		<div class="mb-4 flex flex-wrap items-center gap-3">
			{#if searchQuery === undefined}
				<div class="relative min-w-60 max-w-100 flex-1">
					<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
					<input
						type="text"
						placeholder="Search by name, ID, datasource, or analysis..."
						class="w-full border border-tertiary bg-transparent px-3 py-1.5 pl-8 text-sm"
						bind:value={search}
					/>
				</div>
			{/if}
			<select
				class="border border-tertiary bg-transparent px-3 py-1.5 text-sm"
				bind:value={kindFilter}
			>
				<option value="">All types</option>
				<option value="preview">Preview</option>
				<option value="export">Export</option>
				<option value="datasource_create">Datasource Create</option>
				<option value="datasource_update">Datasource Update</option>
			</select>
			<select
				class="border border-tertiary bg-transparent px-3 py-1.5 text-sm"
				bind:value={statusFilter}
			>
				<option value="">All statuses</option>
				<option value="success">Success</option>
				<option value="failed">Failed</option>
			</select>
			<BranchPicker
				branches={branchOptions}
				value={branchFilter || 'master'}
				placeholder="Branch"
				onChange={(value: string) => (branchFilter = value)}
			/>
			<div class="flex items-center gap-1.5 text-sm">
				<span class="text-fg-muted">From</span>
				<input
					type="date"
					class="border border-tertiary bg-transparent px-2 py-1 text-sm"
					bind:value={dateFrom}
				/>
				<span class="text-fg-muted">To</span>
				<input
					type="date"
					class="border border-tertiary bg-transparent px-2 py-1 text-sm"
					bind:value={dateTo}
				/>
			</div>
		</div>
	{/if}

	{#if query.isLoading}
		<div class="flex h-full items-center justify-center">
			<div class="spinner"></div>
		</div>
	{:else if query.isError}
		<div class="error-box">
			{query.error instanceof Error ? query.error.message : 'Error loading runs.'}
		</div>
	{:else if runs.length === 0}
		<div class="border border-dashed border-tertiary p-8 text-center">
			<p class="text-fg-muted">No engine runs yet.</p>
			<p class="text-sm text-fg-tertiary">
				Runs will appear here when you preview or export data in analyses. Compare builds from the
				Datasources tab.
			</p>
		</div>
	{:else}
		<div class="overflow-x-auto border border-tertiary">
			<table class="w-full border-collapse text-sm">
				<thead>
					<tr class="bg-bg-tertiary">
						<th class="w-8 border-b border-tertiary px-3 py-2 text-left font-medium"></th>
						{#each [{ key: 'kind', label: 'Type' }, { key: 'status', label: 'Status' }, { key: 'datasource', label: 'Datasource' }, { key: 'analysis', label: 'Analysis' }, { key: 'output', label: 'Output' }, { key: 'duration_ms', label: 'Duration' }, { key: 'created_at', label: 'Created' }] as col (col.key)}
							<th
								class="cursor-pointer border-b border-tertiary px-3 py-2 text-left font-medium transition-colors hover:bg-hover"
								onclick={() => toggleSort(col.key)}
							>
								<span class="inline-flex items-center gap-1">
									{col.label}
									{#if sortColumn === col.key}
										{#if sortDir === 'asc'}
											<ArrowUp size={12} />
										{:else}
											<ArrowDown size={12} />
										{/if}
									{/if}
								</span>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each filteredRuns as run (run.id)}
						<tr
							class="cursor-pointer hover:bg-bg-hover"
							class:bg-bg-secondary={expandedId === run.id}
							onclick={() => toggleExpand(run.id)}
						>
							<td class="border-b border-tertiary px-3 py-2">
								<ChevronDown size={14} class={expandedId === run.id ? '' : '-rotate-90'} />
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								<span class="inline-flex items-center gap-1.5">
									{#if run.kind === 'preview'}
										<Eye size={14} class="text-accent" />
										<span>Preview</span>
									{:else if run.kind === 'datasource_create'}
										<Database size={14} class="text-accent-primary" />
										<span>Datasource Create</span>
									{:else if run.kind === 'datasource_update'}
										<RefreshCw size={14} class="text-warning-fg" />
										<span>Datasource Update</span>
									{:else}
										<Download size={14} class="text-success-fg" />
										<span>Export</span>
									{/if}
									{#if run.triggered_by === 'schedule'}
										<span
											class="ml-1 inline-flex items-center gap-0.5 bg-accent-bg px-1 py-0.5 text-xs text-accent-primary"
											title="Triggered by schedule"
										>
											<CalendarClock size={11} />
										</span>
									{/if}
								</span>
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								<span class="inline-flex items-center gap-1.5">
									{#if run.status === 'success'}
										<CircleCheck size={14} class="text-success-fg" />
										<span class="text-success-fg">Success</span>
									{:else}
										<CircleX size={14} class="text-error-fg" />
										<span class="text-error-fg">Failed</span>
									{/if}
								</span>
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								<span class="text-xs text-fg-secondary" title={run.datasource_id}>
									{resolveName(run.datasource_id, dsNames)}
								</span>
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								{#if run.analysis_id}
									<span class="text-xs text-fg-secondary" title={run.analysis_id}>
										{resolveName(run.analysis_id, analysisNames)}
									</span>
								{:else}
									<span class="text-fg-muted">-</span>
								{/if}
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								{#if getOutputName(run)}
									<span class="text-xs text-fg-secondary" title={getOutputName(run) ?? ''}>
										{getOutputName(run)}
									</span>
								{:else}
									<span class="text-fg-muted">-</span>
								{/if}
							</td>
							<td class="border-b border-tertiary px-3 py-2 font-mono text-xs">
								{formatDuration(run.duration_ms)}
							</td>
							<td class="border-b border-tertiary px-3 py-2 text-fg-secondary">
								{formatDate(run.created_at)}
							</td>
						</tr>
						{#if expandedId === run.id}
							<tr>
								<td colspan="8" class="border-b border-tertiary bg-bg-primary p-0">
									<div class="p-4">
										<!-- Tab buttons -->
										<div class="mb-4 flex gap-1 border-b border-tertiary">
											<button
												class="border-b-2 px-3 py-1.5 text-sm -mb-px {activeTab === 'request'
													? 'border-accent-primary text-fg-primary'
													: 'border-transparent text-fg-tertiary hover:text-fg-secondary'}"
												onclick={(e) => {
													e.stopPropagation();
													activeTab = 'request';
												}}
											>
												Request Config
											</button>
											<button
												class="border-b-2 px-3 py-1.5 text-sm -mb-px {activeTab === 'result'
													? 'border-accent-primary text-fg-primary'
													: 'border-transparent text-fg-tertiary hover:text-fg-secondary'}"
												onclick={(e) => {
													e.stopPropagation();
													activeTab = 'result';
												}}
											>
												Result
											</button>
											{#if hasTimings(run)}
												<button
													class="border-b-2 px-3 py-1.5 text-sm -mb-px {activeTab === 'timings'
														? 'border-accent-primary text-fg-primary'
														: 'border-transparent text-fg-tertiary hover:text-fg-secondary'}"
													onclick={(e) => {
														e.stopPropagation();
														activeTab = 'timings';
													}}
												>
													<span class="inline-flex items-center gap-1">
														<Timer size={13} />
														Step Timings
													</span>
												</button>
											{/if}
											{#if hasPlans(run)}
												<button
													class="border-b-2 px-3 py-1.5 text-sm -mb-px {activeTab === 'plans'
														? 'border-accent-primary text-fg-primary'
														: 'border-transparent text-fg-tertiary hover:text-fg-secondary'}"
													onclick={(e) => {
														e.stopPropagation();
														activeTab = 'plans';
													}}
												>
													Query Plans
												</button>
											{/if}
										</div>

										<!-- Tab content -->
										{#if activeTab === 'request'}
											<div class="space-y-3">
												<div class="grid grid-cols-2 gap-4 text-sm">
													<div>
														<span class="text-fg-muted">Run ID:</span>
														<span class="ml-2 font-mono text-xs">{run.id}</span>
													</div>
													<div>
														<span class="text-fg-muted">Datasource:</span>
														<span class="ml-2 text-xs">
															{resolveName(run.datasource_id, dsNames)}
														</span>
													</div>
													{#if run.analysis_id}
														<div>
															<span class="text-fg-muted">Analysis:</span>
															<span class="ml-2 text-xs">
																{resolveName(run.analysis_id, analysisNames)}
															</span>
														</div>
													{/if}
													{#if run.triggered_by}
														<div>
															<span class="text-fg-muted">Triggered by:</span>
															<span
																class="ml-2 inline-flex items-center gap-1 text-xs text-accent-primary"
															>
																<CalendarClock size={12} />
																{run.triggered_by}
															</span>
														</div>
													{/if}
												</div>
												<div>
													<h4 class="mb-2 text-sm font-medium text-fg-secondary">
														Request Payload
													</h4>
													<pre
														class="max-h-80 overflow-x-auto border border-tertiary bg-bg-tertiary p-3 font-mono text-xs">{JSON.stringify(
															run.request_json,
															null,
															2
														)}</pre>
												</div>
											</div>
										{:else if activeTab === 'result'}
											<div class="space-y-3">
												{#if run.status === 'failed' && run.error_message}
													<div class="error-box">
														<h4 class="mb-1 text-sm font-medium">Error</h4>
														<p class="text-sm">{run.error_message}</p>
													</div>
												{/if}
												{#if run.result_json}
													{@const result = run.result_json}
													<div>
														<h4 class="mb-2 text-sm font-medium text-fg-secondary">
															Result Metadata
														</h4>
														<div class="mb-3 grid grid-cols-2 gap-4 text-sm">
															{#if 'row_count' in result}
																<div>
																	<span class="text-fg-muted">Rows:</span>
																	<span class="ml-2 font-mono">{result.row_count}</span>
																</div>
															{/if}
															{#if 'page' in result}
																<div>
																	<span class="text-fg-muted">Page:</span>
																	<span class="ml-2 font-mono">{result.page}</span>
																</div>
															{/if}
															{#if 'page_size' in result}
																<div>
																	<span class="text-fg-muted">Page Size:</span>
																	<span class="ml-2 font-mono">{result.page_size}</span>
																</div>
															{/if}
															{#if 'export_format' in result}
																<div>
																	<span class="text-fg-muted">Format:</span>
																	<span class="ml-2 font-mono">{result.export_format}</span>
																</div>
															{/if}
															{#if 'file_size_bytes' in result}
																<div>
																	<span class="text-fg-muted">File Size:</span>
																	<span class="ml-2 font-mono"
																		>{(Number(result.file_size_bytes) / 1024).toFixed(1)} KB</span
																	>
																</div>
															{/if}
														</div>
														{#if 'schema' in result && result.schema}
															<div>
																<h4 class="mb-2 text-sm font-medium text-fg-secondary">Schema</h4>
																<div
																	class="max-h-40 overflow-x-auto border border-tertiary bg-bg-tertiary p-3 font-mono text-xs"
																>
																	{#each Object.entries(result.schema as Record<string, string>) as [col, dtype] (col)}
																		<div>
																			<span class="text-accent-primary">{col}</span>:
																			<span class="text-fg-muted">{dtype}</span>
																		</div>
																	{/each}
																</div>
															</div>
														{/if}
													</div>
												{:else}
													<p class="text-sm text-fg-muted">No result data available.</p>
												{/if}
											</div>
										{:else if activeTab === 'timings'}
											{@const entries = getTimingEntries(run)}
											<div class="space-y-2">
												<h4 class="mb-3 text-sm font-medium text-fg-secondary">
													Step Execution Timeline
												</h4>
												{#each entries as entry (entry.name)}
													<div class="flex items-center gap-3 text-xs">
														<span
															class="w-36 shrink-0 truncate font-mono text-fg-secondary"
															title={entry.name}
														>
															{entry.name}
														</span>
														<div class="relative h-5 flex-1 bg-bg-tertiary">
															<div
																class="absolute inset-y-0 left-0 bg-accent-bg"
																style="width: {Math.max(entry.pct, 1)}%"
															></div>
														</div>
														<span class="w-16 shrink-0 text-right font-mono text-fg-muted">
															{formatDuration(entry.ms)}
														</span>
													</div>
												{/each}
												{#if entries.length > 0}
													<div
														class="mt-3 border-t border-tertiary pt-2 text-right font-mono text-xs text-fg-muted"
													>
														Total: {formatDuration(run.duration_ms)}
													</div>
												{/if}
											</div>
										{:else if activeTab === 'plans'}
											{@const plans = getQueryPlans(run)}
											{#if plans}
												<div class="space-y-4">
													<div>
														<h4 class="mb-2 text-sm font-medium text-fg-secondary">
															Optimized Plan
														</h4>
														<pre
															class="max-h-60 overflow-x-auto whitespace-pre-wrap border border-tertiary bg-bg-tertiary p-3 font-mono text-xs">{plans.optimized ||
																'N/A'}</pre>
													</div>
													<div>
														<h4 class="mb-2 text-sm font-medium text-fg-secondary">
															Unoptimized Plan
														</h4>
														<pre
															class="max-h-60 overflow-x-auto whitespace-pre-wrap border border-tertiary bg-bg-tertiary p-3 font-mono text-xs">{plans.unoptimized ||
																'N/A'}</pre>
													</div>
												</div>
											{:else}
												<p class="text-sm text-fg-muted">No query plans available for this run.</p>
											{/if}
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>

		<div class="mt-4 flex items-center justify-between">
			<span class="text-sm text-fg-tertiary">
				Page {page}
				{#if filteredRuns.length < runs.length}
					({filteredRuns.length} of {runs.length} shown)
				{/if}
			</span>
			<div class="flex items-center gap-2">
				<button class="btn-ghost btn-sm" onclick={prevPage} disabled={page === 1}>
					<ChevronLeft size={14} />
					Previous
				</button>
				<button class="btn-ghost btn-sm" onclick={nextPage} disabled={filteredRuns.length < limit}>
					Next
					<ChevronRight size={14} />
				</button>
			</div>
		</div>
	{/if}
</div>
