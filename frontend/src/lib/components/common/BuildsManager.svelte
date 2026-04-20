<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import type { EngineRun } from '$lib/api/engine-runs';
	import { cancelBuild } from '$lib/api/compute';
	import { getDatasource, listDatasources } from '$lib/api/datasource';
	import { listAnalyses } from '$lib/api/analysis';
	import type { ActiveBuildDetail } from '$lib/types/build-stream';
	import { getActiveBuildByEngineRun } from '$lib/api/build-stream';
	import { getEngineRun } from '$lib/api/engine-runs';
	import { EngineRunsStore } from '$lib/stores/engine-runs.svelte';
	import { page as pageState } from '$app/state';
	import {
		Search,
		CircleCheck,
		CircleX,
		Loader,
		Download,
		ChevronLeft,
		ChevronRight,
		ChevronDown,
		ArrowUp,
		ArrowDown,
		CalendarClock,
		Database,
		RefreshCw,
		Hash
	} from 'lucide-svelte';
	import BranchPicker from '$lib/components/common/BranchPicker.svelte';
	import BuildPreview from '$lib/components/common/BuildPreview.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { BuildStreamStore } from '$lib/stores/build-stream.svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import { css, spinner, button, emptyText, input } from '$lib/styles/panda';
	import {
		engineRunBuildDetail,
		engineRunCurrentTabName,
		engineRunDatasourceId,
		engineRunDatasourceName,
		engineRunOutputName,
		engineRunStatus
	} from '$lib/utils/engine-run-build-detail';

	interface Props {
		compact?: boolean;
		searchQuery?: string;
		embedded?: boolean;
	}

	type CancelTarget = {
		id: string;
	};

	let { compact = false, searchQuery, embedded = false }: Props = $props();

	let search = $state('');
	const effectiveSearch = $derived(searchQuery ?? search);
	let kindFilter = $state<string>('');
	let statusFilter = $state<'all' | 'running' | 'completed' | 'failed' | 'cancelled'>('all');
	let cancelTarget = $state<CancelTarget | null>(null);
	let cancelPending = $state(false);
	let cancelError = $state<string | null>(null);
	let dateFrom = $state('');
	let dateTo = $state('');
	let page = $state(1);
	let branchFilter = $state('');
	let expandedId = $state<string | null>(null);
	let expandedLiveId = $state<string | null>(null);
	let expandedStore = $state<BuildStreamStore | null>(null);
	let sortColumn = $state<string>('created_at');
	let sortDir = $state<'asc' | 'desc'>('desc');
	const runDetailStores = new SvelteMap<string, BuildStreamStore>();
	const limit = 50;

	const queryParams = $derived({
		analysis_id: (pageState.url.searchParams.get('analysis_id') ?? undefined) || undefined,
		datasource_id: (pageState.url.searchParams.get('datasource_id') ?? undefined) || undefined,
		kind: kindFilter || undefined,
		status:
			statusFilter === 'running'
				? ('running' as const)
				: statusFilter === 'completed'
					? ('success' as const)
					: statusFilter === 'failed'
						? ('failed' as const)
						: statusFilter === 'cancelled'
							? ('cancelled' as const)
							: undefined,
		limit,
		offset: (page - 1) * limit
	});

	const engineRunsStore = new EngineRunsStore();

	// Network: fetch build history when filters change.
	$effect(() => {
		const params = queryParams;
		engineRunsStore.load(params);
		return () => engineRunsStore.close();
	});

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 60_000
	}));

	const analysesQuery = createQuery(() => ({
		queryKey: ['analyses-lookup'],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) throw new Error(result.error.message);
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

	const runs = $derived(engineRunsStore.runs);

	const datasourceId = $derived(
		(pageState.url.searchParams.get('datasource_id') ?? undefined) || undefined
	);
	const datasourceQuery = createQuery(() => ({
		queryKey: ['datasource', datasourceId],
		queryFn: async () => {
			if (!datasourceId) return null;
			const result = await getDatasource(datasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasourceId
	}));
	const branchOptions = $derived.by(() => {
		const config = (datasourceQuery.data?.config ?? {}) as Record<string, unknown>;
		const branches = (config.branches as string[] | undefined) ?? [];
		const cleaned = branches.map((branch) => branch.trim()).filter((branch) => branch.length > 0);
		const set = new SvelteSet<string>();
		set.add('master');
		for (const branch of cleaned) set.add(branch);
		return Array.from(set).sort((a, b) => a.localeCompare(b));
	});

	const filteredRuns = $derived.by(() => {
		let result = runs.filter((run) => run.kind !== 'preview');

		if (effectiveSearch) {
			const q = effectiveSearch.toLowerCase();
			result = result.filter((run) => {
				const outputName = engineRunOutputName(run) ?? '';
				const currentTabName = engineRunCurrentTabName(run) ?? '';
				return (
					run.id.toLowerCase().includes(q) ||
					engineRunDatasourceId(run).toLowerCase().includes(q) ||
					(run.analysis_id?.toLowerCase().includes(q) ?? false) ||
					(engineRunDatasourceName(run) ?? dsNames.get(engineRunDatasourceId(run)) ?? '')
						.toLowerCase()
						.includes(q) ||
					(run.analysis_id
						? (analysisNames.get(run.analysis_id) ?? '').toLowerCase().includes(q)
						: false) ||
					outputName.toLowerCase().includes(q) ||
					currentTabName.toLowerCase().includes(q) ||
					(run.current_step ?? '').toLowerCase().includes(q)
				);
			});
		}

		if (dateFrom) {
			const from = new Date(dateFrom);
			result = result.filter((run) => new Date(run.created_at) >= from);
		}
		if (dateTo) {
			// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local Date for comparison, not reactive state
			const to = new Date(dateTo);
			to.setHours(23, 59, 59, 999);
			result = result.filter((run) => new Date(run.created_at) <= to);
		}

		if (branchFilter) {
			result = result.filter((run) => getRunBranch(run) === branchFilter);
		}

		return sortRuns(result);
	});

	const hasAnyBuildRows = $derived(filteredRuns.length > 0);

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
				return dir * engineRunStatus(a).localeCompare(engineRunStatus(b));
			}
			if (sortColumn === 'datasource') {
				const left =
					engineRunDatasourceName(a) ??
					dsNames.get(engineRunDatasourceId(a)) ??
					engineRunDatasourceId(a);
				const right =
					engineRunDatasourceName(b) ??
					dsNames.get(engineRunDatasourceId(b)) ??
					engineRunDatasourceId(b);
				return dir * left.localeCompare(right);
			}
			if (sortColumn === 'analysis') {
				const left = a.analysis_id ? (analysisNames.get(a.analysis_id) ?? a.analysis_id) : '';
				const right = b.analysis_id ? (analysisNames.get(b.analysis_id) ?? b.analysis_id) : '';
				return dir * left.localeCompare(right);
			}
			if (sortColumn === 'output') {
				const left = engineRunOutputName(a) ?? '';
				const right = engineRunOutputName(b) ?? '';
				return dir * left.localeCompare(right);
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
		return new Date(isoDate).toLocaleString();
	}

	function prevPage() {
		if (page > 1) page--;
	}

	function nextPage() {
		if (filteredRuns.length >= limit) page++;
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function resolveName(id: string, map: Map<string, string>): string {
		return map.get(id) ?? `${id.slice(0, 8)}...`;
	}

	function getKindLabel(kind: string): string {
		if (kind === 'preview') return 'Preview';
		if (kind === 'download') return 'Download';
		if (kind === 'datasource_create') return 'Output Create';
		if (kind === 'datasource_update') return 'Output Update';
		if (kind === 'row_count') return 'Row Count';
		return kind;
	}

	function getRunBranch(run: EngineRun): string | null {
		const payload = run.request_json as Record<string, unknown>;
		const opts = payload.iceberg_options as Record<string, unknown> | undefined;
		if (typeof opts?.branch === 'string' && opts.branch.trim()) return opts.branch;

		const datasource = payload.datasource_config as Record<string, unknown> | undefined;
		if (typeof datasource?.branch === 'string' && datasource.branch.trim())
			return datasource.branch;

		const result = run.result_json as Record<string, unknown> | null;
		const meta = result?.metadata as Record<string, unknown> | undefined;
		if (typeof meta?.branch === 'string' && meta.branch.trim()) return meta.branch;

		return null;
	}

	function runStatusLabel(run: EngineRun): string {
		const status = engineRunStatus(run);
		if (status === 'running') return 'Running';
		if (status === 'completed') return 'Success';
		if (status === 'cancelled') return 'Cancelled';
		return 'Failed';
	}

	function readResultString(run: EngineRun, key: string): string | null {
		if (!run.result_json) return null;
		const value = run.result_json[key];
		return typeof value === 'string' && value.length > 0 ? value : null;
	}

	function cancelledAt(run: EngineRun): string | null {
		return readResultString(run, 'cancelled_at');
	}

	function cancelledBy(run: EngineRun): string | null {
		return readResultString(run, 'cancelled_by');
	}

	function lastCompletedStep(run: EngineRun): string | null {
		return readResultString(run, 'last_completed_step');
	}

	function canCancelRun(run: EngineRun): boolean {
		return run.status === 'running';
	}

	function requestCancelRun(run: EngineRun): void {
		if (!canCancelRun(run) || cancelPending) return;
		cancelError = null;
		cancelTarget = { id: run.id };
	}

	function closeCancelDialog(): void {
		if (cancelPending) return;
		cancelTarget = null;
	}

	async function confirmCancelRun(): Promise<void> {
		const target = cancelTarget;
		if (!target || cancelPending) return;
		cancelPending = true;
		cancelError = null;
		const result = await cancelBuild(target.id);
		result.match(
			() => {
				cancelTarget = null;
			},
			(err) => {
				cancelError = err.message;
			}
		);
		cancelPending = false;
	}

	async function refreshHistory(): Promise<void> {
		engineRunsStore.refresh();
	}

	function runDetailStore(run: EngineRun): BuildStreamStore {
		let store = runDetailStores.get(run.id);
		if (!store) {
			store = new BuildStreamStore();
			runDetailStores.set(run.id, store);
		}
		store.applySnapshot(engineRunBuildDetail(run));
		return store;
	}

	function replaceRun(next: EngineRun): void {
		engineRunsStore.replaceRun(next);
	}

	async function syncExpandedRun(runId: string): Promise<void> {
		const run = runs.find((item) => item.id === runId);
		if (!run) return;
		const store = runDetailStore(run);
		if (engineRunStatus(run) !== 'running') {
			store.close();
			store.applySnapshot(engineRunBuildDetail(run));
			expandedLiveId = null;
			expandedStore = store;
			return;
		}
		const live = await getActiveBuildByEngineRun(run.id).match(
			(detail: ActiveBuildDetail) => detail,
			() => null
		);
		if (expandedId !== runId) return;
		if (!live) {
			const persisted = await getEngineRun(run.id).match(
				(r: EngineRun) => r,
				() => null
			);
			if (expandedId !== runId) return;
			const source = persisted ?? run;
			if (persisted) replaceRun(persisted);
			store.close();
			store.applySnapshot(engineRunBuildDetail(source));
			expandedLiveId = null;
			expandedStore = store;
			return;
		}
		store.watch(live.build_id);
		store.applySnapshot(live);
		expandedLiveId = runId;
		expandedStore = store;
	}

	// Side effect: mutates expandedStore state and binds live detail only for expanded running rows.
	$effect(() => {
		for (const [runId, store] of runDetailStores) {
			if (runId === expandedId) continue;
			store.close();
		}
		const expandedRun = runs.find((run) => run.id === expandedId) ?? null;
		if (!expandedRun) {
			expandedLiveId = null;
			expandedStore = null;
			return;
		}
		void syncExpandedRun(expandedRun.id);
	});

	// Side effect: when a live row reaches terminal state, replace that row with persisted history once.
	$effect(() => {
		const liveId = expandedLiveId;
		const store = expandedStore;
		if (!liveId || !store || !store.done || !store.engineRunId) return;
		expandedLiveId = null;
		void getEngineRun(store.engineRunId).match(
			(persisted) => {
				if (expandedId !== liveId) return;
				store.close();
				replaceRun(persisted);
				store.applySnapshot(engineRunBuildDetail(persisted));
				expandedStore = store;
			},
			(err) => {
				console.warn('Failed to fetch persisted run after build done:', err.message);
			}
		);
	});

	// Side effect: when a live stream disconnects (WS endpoint gone), recover from persisted state.
	$effect(() => {
		const liveId = expandedLiveId;
		const store = expandedStore;
		if (!liveId || !store || store.status !== 'disconnected') return;
		if (store.done) return;
		expandedLiveId = null;
		const engineRunId = store.engineRunId;
		if (!engineRunId) return;
		void getEngineRun(engineRunId).match(
			(persisted) => {
				if (expandedId !== liveId) return;
				store.close();
				replaceRun(persisted);
				store.applySnapshot(engineRunBuildDetail(persisted));
				expandedStore = store;
			},
			(err) => {
				console.warn('Failed to fetch persisted run after WS disconnect:', err.message);
			}
		);
	});

	// Side effect: cleanup callback to close WebSocket stores on component destroy
	$effect(() => {
		const target = cancelTarget;
		if (!target) return;
		const latest = runs.find((run) => run.id === target.id);
		if (!latest || latest.status !== 'running') {
			cancelTarget = null;
			cancelPending = false;
		}
	});

	$effect(() => {
		return () => {
			for (const store of runDetailStores.values()) {
				store.close();
			}
			runDetailStores.clear();
		};
	});
</script>

<div
	class={css({
		display: 'flex',
		flexDirection: 'column',
		height: '100%',
		width: '100%'
	})}
	data-builds-page
>
	{#if !compact && !embedded}
		<header
			class={css({
				marginBottom: '6',
				borderBottomWidth: '1',
				paddingBottom: '5'
			})}
		>
			<h1 class={css({ margin: '0', marginBottom: '2', fontSize: '2xl' })}>Builds</h1>
			<p class={css({ margin: '0', color: 'fg.tertiary' })}>
				Engine run history for previews and exports
			</p>
		</header>
	{/if}

	{#if compact}
		{#if searchQuery === undefined}
			<div class={css({ display: 'flex', alignItems: 'center', marginBottom: '3', gap: '2' })}>
				<div class={css({ position: 'relative', minWidth: 'list', flex: '1' })}>
					<Search
						size={14}
						class={css({
							position: 'absolute',
							left: '2.5',
							top: '50%',
							transform: 'translateY(-50%)',
							color: 'fg.muted'
						})}
					/>
					<input
						type="text"
						id="builds-search"
						aria-label="Search builds"
						placeholder="Search builds..."
						class={input({ variant: 'search' })}
						bind:value={search}
					/>
				</div>
			</div>
		{/if}
	{:else}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginBottom: '4',
				flexWrap: 'wrap',
				gap: '3'
			})}
		>
			{#if searchQuery === undefined}
				<div class={css({ position: 'relative', minWidth: 'list', maxWidth: 'panel', flex: '1' })}>
					<Search
						size={14}
						class={css({
							position: 'absolute',
							left: '2.5',
							top: '50%',
							transform: 'translateY(-50%)',
							color: 'fg.muted'
						})}
					/>
					<input
						type="text"
						id="builds-search-full"
						aria-label="Search builds"
						placeholder="Search by name, ID, datasource, or analysis..."
						class={input({ variant: 'search' })}
						bind:value={search}
					/>
				</div>
			{/if}
			<select
				class={css({
					width: 'full',
					borderWidth: '1',
					borderRadius: '0',
					transitionProperty: 'border-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_focus: { outline: 'none' },
					_focusVisible: { borderColor: 'border.accent' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
					_placeholder: { color: 'fg.muted' },
					paddingX: '3',
					paddingY: '1.5',
					fontSize: 'sm',
					'& option:checked': {
						backgroundColor: 'bg.accent',
						color: 'accent.primary'
					}
				})}
				id="builds-kind-filter"
				aria-label="Filter by type"
				bind:value={kindFilter}
			>
				<option value="">All types</option>
				<option value="download">Download</option>
				<option value="datasource_create">Output Create</option>
				<option value="datasource_update">Output Update</option>
				<option value="row_count">Row Count</option>
			</select>
			<select
				class={css({
					width: 'full',
					borderWidth: '1',
					borderRadius: '0',
					transitionProperty: 'border-color',
					transitionDuration: '160ms',
					transitionTimingFunction: 'ease',
					_focus: { outline: 'none' },
					_focusVisible: { borderColor: 'border.accent' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
					_placeholder: { color: 'fg.muted' },
					paddingX: '3',
					paddingY: '1.5',
					fontSize: 'sm',
					'& option:checked': {
						backgroundColor: 'bg.accent',
						color: 'accent.primary'
					}
				})}
				id="builds-status-filter"
				aria-label="Filter by status"
				bind:value={statusFilter}
			>
				<option value="all">All statuses</option>
				<option value="running">Running</option>
				<option value="completed">Completed</option>
				<option value="failed">Failed</option>
				<option value="cancelled">Cancelled</option>
			</select>
			<BranchPicker
				branches={branchOptions}
				value={branchFilter}
				placeholder="Branch"
				onChange={(value: string) => (branchFilter = value)}
			/>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5', fontSize: 'sm' })}>
				<span class={css({ color: 'fg.muted' })}>From</span>
				<input
					type="date"
					class={css({
						width: 'full',
						fontSize: 'sm',
						color: 'fg.primary',
						backgroundColor: 'bg.primary',
						borderWidth: '1',
						borderRadius: '0',
						paddingX: '3.5',
						paddingY: '1',
						cursor: 'pointer',
						transitionProperty: 'border-color',
						transitionDuration: '160ms',
						transitionTimingFunction: 'ease',
						_focus: { outline: 'none' },
						_focusVisible: { borderColor: 'border.accent' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
						_placeholder: { color: 'fg.muted' }
					})}
					id="builds-date-from"
					aria-label="From date"
					bind:value={dateFrom}
				/>
				<span class={css({ color: 'fg.muted' })}>To</span>
				<input
					type="date"
					class={css({
						width: 'full',
						fontSize: 'sm',
						color: 'fg.primary',
						backgroundColor: 'bg.primary',
						borderWidth: '1',
						borderRadius: '0',
						paddingX: '3.5',
						paddingY: '1',
						cursor: 'pointer',
						transitionProperty: 'border-color',
						transitionDuration: '160ms',
						transitionTimingFunction: 'ease',
						_focus: { outline: 'none' },
						_focusVisible: { borderColor: 'border.accent' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
						_placeholder: { color: 'fg.muted' }
					})}
					id="builds-date-to"
					aria-label="To date"
					bind:value={dateTo}
				/>
			</div>
			<button
				type="button"
				class={button({ variant: 'ghost', size: 'sm' })}
				onclick={() => void refreshHistory()}
			>
				<RefreshCw size={14} />
				Refresh History
			</button>
		</div>
	{/if}

	{#if engineRunsStore.status === 'connecting'}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				height: '100%',
				justifyContent: 'center'
			})}
		>
			<div class={spinner()}></div>
		</div>
	{:else if engineRunsStore.status === 'error'}
		<div
			data-testid="stream-error"
			class={css({
				paddingX: '3',
				paddingY: '2.5',
				border: 'none',
				borderLeftWidth: '2',

				marginTop: '3',
				marginBottom: '0',
				fontSize: 'xs',
				lineHeight: '1.5',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.error',
				color: 'fg.error'
			})}
		>
			{engineRunsStore.error ?? 'Failed to load builds'}
		</div>
	{:else if !hasAnyBuildRows}
		<div
			class={css({
				borderWidth: '1',
				borderStyle: 'dashed',
				padding: '8',
				textAlign: 'center'
			})}
		>
			<p class={emptyText({ size: 'panel' })}>No builds yet.</p>
			<p class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
				Runs will appear here when you preview or export data in analyses. Compare builds from the
				Datasources tab.
			</p>
		</div>
	{:else}
		<div
			class={css({
				overflowX: 'auto',
				borderWidth: '1'
			})}
		>
			<table
				class={css({
					width: '100%',
					borderCollapse: 'collapse',
					tableLayout: 'fixed',
					fontSize: 'sm'
				})}
			>
				<colgroup>
					<col style="width: 40px;" />
					<col style="width: 180px;" />
					<col style="width: 130px;" />
					<col style="width: 240px;" />
					<col style="width: 120px;" />
					<col style="width: 220px;" />
					<col style="width: 110px;" />
					<col style="width: 190px;" />
				</colgroup>
				<thead>
					<tr class={css({ backgroundColor: 'bg.tertiary' })}>
						<th
							class={css({
								width: 'rowLg',
								borderBottomWidth: '1',
								paddingX: '3',
								paddingY: '2',
								textAlign: 'left',
								fontWeight: 'medium'
							})}
						></th>
						{#each [{ key: 'kind', label: 'Type' }, { key: 'status', label: 'Status' }, { key: 'datasource', label: 'Datasource' }, { key: 'analysis', label: 'Analysis' }, { key: 'output', label: 'Output' }, { key: 'duration_ms', label: 'Duration' }, { key: 'created_at', label: 'Created' }] as col (col.key)}
							<th
								class={css({
									cursor: 'pointer',
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2',
									textAlign: 'left',
									fontWeight: 'medium',
									transition: 'background-color 160ms ease',
									_hover: {
										backgroundColor: 'bg.hover'
									}
								})}
								onclick={() => toggleSort(col.key)}
							>
								<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1' })}>
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
							data-build-row={run.id}
							data-build-source="history"
							data-build-status={engineRunStatus(run)}
							data-build-kind={run.kind}
							data-build-datasource-id={engineRunDatasourceId(run)}
							data-build-datasource-name={engineRunDatasourceName(run) ??
								resolveName(engineRunDatasourceId(run), dsNames)}
							data-build-analysis-id={run.analysis_id ?? ''}
							data-build-analysis-name={run.analysis_id
								? resolveName(run.analysis_id, analysisNames)
								: ''}
							data-build-output-name={engineRunOutputName(run) ?? ''}
							class={css(
								{
									cursor: 'pointer',
									_hover: { backgroundColor: 'bg.hover' }
								},
								expandedId === run.id && { backgroundColor: 'bg.secondary' }
							)}
							onclick={() => toggleExpand(run.id)}
						>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2'
								})}
							>
								<ChevronDown
									size={14}
									class={expandedId === run.id ? undefined : css({ transform: 'rotate(-90deg)' })}
								/>
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2'
								})}
							>
								<span
									class={[
										css({
											display: 'block',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap'
										}),
										css({
											display: 'inline-flex',
											alignItems: 'center',
											gap: '1.5'
										})
									]}
								>
									{#if run.kind === 'datasource_create'}
										<Database size={14} class={css({ color: 'accent.primary' })} />
										<span>{getKindLabel(run.kind)}</span>
									{:else if run.kind === 'datasource_update'}
										<RefreshCw size={14} class={css({ color: 'fg.warning' })} />
										<span>{getKindLabel(run.kind)}</span>
									{:else if run.kind === 'download'}
										<Download size={14} class={css({ color: 'fg.success' })} />
										<span>{getKindLabel(run.kind)}</span>
									{:else if run.kind === 'row_count'}
										<Hash size={14} class={css({ color: 'fg.muted' })} />
										<span>{getKindLabel(run.kind)}</span>
									{:else}
										<Database size={14} class={css({ color: 'fg.muted' })} />
										<span>{getKindLabel(run.kind)}</span>
									{/if}
									{#if run.triggered_by === 'schedule'}
										<span
											class={css({
												marginLeft: '1',
												display: 'inline-flex',
												alignItems: 'center',
												gap: '0.5',
												backgroundColor: 'bg.accent',
												paddingX: '1',
												paddingY: '0.5',
												fontSize: 'xs',
												color: 'accent.primary'
											})}
											title="Triggered by schedule"
										>
											<CalendarClock size={11} />
										</span>
									{/if}
								</span>
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2'
								})}
							>
								<div
									class={css({
										display: 'flex',
										alignItems: 'center',
										justifyContent: 'space-between',
										gap: '2'
									})}
								>
									<span
										class={[
											css({
												display: 'block',
												overflow: 'hidden',
												textOverflow: 'ellipsis',
												whiteSpace: 'nowrap'
											}),
											css({
												display: 'inline-flex',
												alignItems: 'center',
												gap: '1.5'
											})
										]}
									>
										{#if engineRunStatus(run) === 'running'}
											<Loader
												size={14}
												class={css({
													color: 'accent.primary',
													animation: 'spin 1s linear infinite'
												})}
											/>
											<span class={css({ color: 'accent.primary' })}>{runStatusLabel(run)}</span>
										{:else if engineRunStatus(run) === 'completed'}
											<CircleCheck size={14} class={css({ color: 'fg.success' })} />
											<span class={css({ color: 'fg.success' })}>{runStatusLabel(run)}</span>
										{:else if engineRunStatus(run) === 'cancelled'}
											<CircleX size={14} class={css({ color: 'fg.warning' })} />
											<span class={css({ color: 'fg.warning' })}>{runStatusLabel(run)}</span>
										{:else}
											<CircleX size={14} class={css({ color: 'fg.error' })} />
											<span class={css({ color: 'fg.error' })}>{runStatusLabel(run)}</span>
										{/if}
									</span>
									{#if canCancelRun(run)}
										<button
											type="button"
											class={button({ variant: 'ghost', size: 'sm' })}
											onclick={(event) => {
												event.stopPropagation();
												requestCancelRun(run);
											}}
											disabled={cancelPending}
											aria-label="Cancel build"
											data-testid={`build-row-cancel-${run.id}`}
										>
											<CircleX size={12} />
										</button>
									{/if}
								</div>
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2'
								})}
							>
								<span
									class={css({
										display: 'block',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										fontSize: 'xs',
										color: 'fg.secondary'
									})}
									title={engineRunDatasourceId(run)}
								>
									{engineRunDatasourceName(run) ?? resolveName(engineRunDatasourceId(run), dsNames)}
								</span>
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2'
								})}
							>
								{#if run.analysis_id}
									<span
										class={css({
											display: 'block',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											fontSize: 'xs',
											color: 'fg.secondary'
										})}
										title={run.analysis_id}
									>
										{resolveName(run.analysis_id, analysisNames)}
									</span>
								{:else}
									<span class={css({ color: 'fg.muted' })}>-</span>
								{/if}
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2'
								})}
							>
								{#if engineRunOutputName(run)}
									<span
										class={css({
											display: 'block',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											fontSize: 'xs',
											color: 'fg.secondary'
										})}
										title={engineRunOutputName(run) ?? ''}
									>
										{engineRunOutputName(run)}
									</span>
								{:else}
									<span class={css({ color: 'fg.muted' })}>-</span>
								{/if}
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2',
									fontFamily: 'mono',
									fontSize: 'xs',
									whiteSpace: 'nowrap'
								})}
							>
								{formatDuration(run.duration_ms)}
							</td>
							<td
								class={css({
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2',
									color: 'fg.secondary',
									whiteSpace: 'nowrap'
								})}
							>
								{formatDate(run.created_at)}
							</td>
						</tr>
						{#if expandedId === run.id}
							<tr data-build-detail={run.id}>
								<td
									colspan="8"
									class={css({
										borderBottomWidth: '1',
										backgroundColor: 'bg.primary',
										padding: '0',
										overflow: 'hidden'
									})}
								>
									<div
										class={css({
											padding: '4',
											display: 'flex',
											flexDirection: 'column',
											gap: '3'
										})}
									>
										<div
											class={css({ display: 'flex', flexWrap: 'wrap', gap: '4', fontSize: 'sm' })}
										>
											<span class={css({ color: 'fg.secondary' })}>
												<strong>Run ID:</strong>
												{run.id}
											</span>
											{#if engineRunStatus(run) === 'cancelled'}
												<span class={css({ color: 'fg.warning' })}>
													<strong>Cancelled At:</strong>
													{cancelledAt(run) ? formatDate(cancelledAt(run) ?? '') : '-'}
												</span>
												<span class={css({ color: 'fg.warning' })}>
													<strong>Cancelled By:</strong>
													{cancelledBy(run) ?? '-'}
												</span>
												<span class={css({ color: 'fg.warning' })}>
													<strong>Last Completed Step:</strong>
													{lastCompletedStep(run) ?? '-'}
												</span>
											{/if}
										</div>
									</div>

									{#if expandedStore}
										<div class={css({ width: '100%', overflowX: 'hidden' })}>
											<BuildPreview
												store={expandedStore}
												title={getKindLabel(run.kind)}
												requestJson={run.request_json}
												resultJson={run.result_json}
											/>
										</div>
									{/if}
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>

		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				marginTop: '4',
				justifyContent: 'space-between'
			})}
		>
			<span class={css({ fontSize: 'sm', color: 'fg.tertiary' })}>
				Page {page}
				{#if filteredRuns.length < runs.length}
					({filteredRuns.length} of {runs.length} shown)
				{/if}
			</span>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				<button
					class={button({ variant: 'ghost', size: 'sm' })}
					onclick={prevPage}
					disabled={page === 1}
				>
					<ChevronLeft size={14} />
					Previous
				</button>
				<button
					class={button({ variant: 'ghost', size: 'sm' })}
					onclick={nextPage}
					disabled={filteredRuns.length < limit}
				>
					Next
					<ChevronRight size={14} />
				</button>
			</div>
		</div>
	{/if}
</div>

<ConfirmDialog
	show={cancelTarget !== null}
	heading="Cancel this build?"
	message="Cancel this build? Any partial results will be discarded."
	confirmText={cancelPending ? 'Cancelling...' : 'Cancel Build'}
	cancelText="Keep running"
	onConfirm={confirmCancelRun}
	onCancel={closeCancelDialog}
/>

{#if cancelError}
	<div
		class={css({
			marginTop: '2',
			borderWidth: '1',
			borderColor: 'border.error',
			backgroundColor: 'bg.error',
			paddingX: '3',
			paddingY: '2',
			fontSize: 'xs',
			color: 'fg.error'
		})}
		data-testid="build-cancel-error"
	>
		{cancelError}
	</div>
{/if}
