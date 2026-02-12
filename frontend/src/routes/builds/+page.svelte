<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { listEngineRuns, type EngineRun, type ListEngineRunsParams } from '$lib/api/engine-runs';
	import {
		Search,
		CircleCheck,
		CircleX,
		Eye,
		Download,
		ChevronLeft,
		ChevronRight,
		ChevronDown
	} from 'lucide-svelte';

	let search = $state('');
	let kindFilter = $state<string>('');
	let statusFilter = $state<'success' | 'failed' | ''>('');
	let page = $state(1);
	let expandedId = $state<string | null>(null);
	let activeTab = $state<'request' | 'result' | 'plans'>('request');
	const limit = 50;

	const params = $derived({
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

	const runs = $derived(query.data ?? []);

	const filteredRuns = $derived(
		search
			? runs.filter(
					(r) =>
						r.id.toLowerCase().includes(search.toLowerCase()) ||
						r.datasource_id.toLowerCase().includes(search.toLowerCase()) ||
						(r.analysis_id && r.analysis_id.toLowerCase().includes(search.toLowerCase()))
				)
			: runs
	);

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
		if (runs.length === limit) page++;
	}

	function toggleExpand(id: string) {
		if (expandedId === id) {
			expandedId = null;
		} else {
			expandedId = id;
			activeTab = 'request';
		}
	}

	function getQueryPlans(run: EngineRun): { optimized: string; unoptimized: string } | null {
		const result = run.result_json;
		if (!result || typeof result !== 'object') return null;
		const plans = result.query_plans as { optimized?: string; unoptimized?: string } | undefined;
		if (!plans) return null;
		return {
			optimized: plans.optimized ?? '',
			unoptimized: plans.unoptimized ?? ''
		};
	}

	function hasPlans(run: EngineRun): boolean {
		return getQueryPlans(run) !== null;
	}
</script>

<div class="builds-page mx-auto max-w-300 px-6 py-7">
	<header class="mb-6 border-b border-tertiary pb-5">
		<h1 class="m-0 mb-2 text-2xl">Builds</h1>
		<p class="m-0 text-fg-tertiary">Engine run history for previews and exports</p>
	</header>

	<div class="mb-4 flex flex-wrap items-center gap-3">
		<div class="relative flex-1 min-w-60 max-w-100">
			<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
			<input
				type="text"
				placeholder="Search by ID, datasource, or analysis..."
				class="w-full bg-transparent border border-tertiary px-3 py-1.5 pl-8 text-sm"
				bind:value={search}
			/>
		</div>
		<select
			class="border border-tertiary bg-transparent px-3 py-1.5 text-sm"
			bind:value={kindFilter}
		>
			<option value="">All types</option>
			<option value="preview">Preview</option>
			<option value="export">Export</option>
		</select>
		<select
			class="border border-tertiary bg-transparent px-3 py-1.5 text-sm"
			bind:value={statusFilter}
		>
			<option value="">All statuses</option>
			<option value="success">Success</option>
			<option value="failed">Failed</option>
		</select>
	</div>

	{#if query.isLoading}
		<div class="flex h-full items-center justify-center">
			<div class="spinner"></div>
		</div>
	{:else if query.isError}
		<div class="error-box">
			{query.error instanceof Error ? query.error.message : 'Error loading runs.'}
		</div>
	{:else if runs.length === 0}
		<div class="rounded-sm border border-dashed border-tertiary p-8 text-center">
			<p class="text-fg-muted">No engine runs yet.</p>
			<p class="text-sm text-fg-tertiary">
				Runs will appear here when you preview or export data in analyses.
			</p>
		</div>
	{:else}
		<div class="overflow-x-auto border border-tertiary">
			<table class="w-full border-collapse text-sm">
				<thead>
					<tr class="bg-bg-tertiary">
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium w-8"></th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Type</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Status</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Datasource</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Analysis</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Duration</th>
						<th class="border-b border-tertiary px-3 py-2 text-left font-medium">Created</th>
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
									{:else}
										<Download size={14} class="text-success-fg" />
										<span>Export</span>
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
								<span class="font-mono text-xs text-fg-secondary" title={run.datasource_id}>
									{run.datasource_id.slice(0, 8)}...
								</span>
							</td>
							<td class="border-b border-tertiary px-3 py-2">
								{#if run.analysis_id}
									<span class="font-mono text-xs text-fg-secondary" title={run.analysis_id}>
										{run.analysis_id.slice(0, 8)}...
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
								<td colspan="7" class="border-b border-tertiary bg-bg-primary p-0">
									<div class="p-4">
										<!-- Tab buttons -->
										<div class="flex gap-1 mb-4 border-b border-tertiary">
											<button
												class="px-3 py-1.5 text-sm border-b-2 -mb-px {activeTab === 'request'
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
												class="px-3 py-1.5 text-sm border-b-2 -mb-px {activeTab === 'result'
													? 'border-accent-primary text-fg-primary'
													: 'border-transparent text-fg-tertiary hover:text-fg-secondary'}"
												onclick={(e) => {
													e.stopPropagation();
													activeTab = 'result';
												}}
											>
												Result
											</button>
											{#if hasPlans(run)}
												<button
													class="px-3 py-1.5 text-sm border-b-2 -mb-px {activeTab === 'plans'
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
														<span class="ml-2 font-mono text-xs">{run.datasource_id}</span>
													</div>
													{#if run.analysis_id}
														<div>
															<span class="text-fg-muted">Analysis:</span>
															<span class="ml-2 font-mono text-xs">{run.analysis_id}</span>
														</div>
													{/if}
												</div>
												<div>
													<h4 class="text-sm font-medium text-fg-secondary mb-2">
														Request Payload
													</h4>
													<pre
														class="bg-bg-tertiary border border-tertiary p-3 text-xs font-mono overflow-x-auto max-h-80">{JSON.stringify(
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
														<h4 class="text-sm font-medium mb-1">Error</h4>
														<p class="text-sm">{run.error_message}</p>
													</div>
												{/if}
												{#if run.result_json}
													{@const result = run.result_json}
													<div>
														<h4 class="text-sm font-medium text-fg-secondary mb-2">
															Result Metadata
														</h4>
														<div class="grid grid-cols-2 gap-4 text-sm mb-3">
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
																<h4 class="text-sm font-medium text-fg-secondary mb-2">Schema</h4>
																<div
																	class="bg-bg-tertiary border border-tertiary p-3 text-xs font-mono overflow-x-auto max-h-40"
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
													<p class="text-fg-muted text-sm">No result data available.</p>
												{/if}
											</div>
										{:else if activeTab === 'plans'}
											{@const plans = getQueryPlans(run)}
											{#if plans}
												<div class="space-y-4">
													<div>
														<h4 class="text-sm font-medium text-fg-secondary mb-2">
															Optimized Plan
														</h4>
														<pre
															class="bg-bg-tertiary border border-tertiary p-3 text-xs font-mono overflow-x-auto max-h-60 whitespace-pre-wrap">{plans.optimized ||
																'N/A'}</pre>
													</div>
													<div>
														<h4 class="text-sm font-medium text-fg-secondary mb-2">
															Unoptimized Plan
														</h4>
														<pre
															class="bg-bg-tertiary border border-tertiary p-3 text-xs font-mono overflow-x-auto max-h-60 whitespace-pre-wrap">{plans.unoptimized ||
																'N/A'}</pre>
													</div>
												</div>
											{:else}
												<p class="text-fg-muted text-sm">No query plans available for this run.</p>
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
				<button class="btn-ghost btn-sm" onclick={nextPage} disabled={runs.length < limit}>
					Next
					<ChevronRight size={14} />
				</button>
			</div>
		</div>
	{/if}
</div>
