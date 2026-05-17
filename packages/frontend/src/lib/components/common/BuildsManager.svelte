<script lang="ts">
	import { tick } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { cancelBuild, type CancelBuildResponse } from '$lib/api/compute';
	import { getBuild } from '$lib/api/builds';
	import { getDatasource, listDatasources } from '$lib/api/datasource';
	import { listAnalyses } from '$lib/api/analysis';
	import { listEngineRuns, type EngineRun, type ListEngineRunsParams } from '$lib/api/engine-runs';
	import type { ActiveBuildDetail, ActiveBuildSummary } from '$lib/types/build-stream';
	import {
		activeBuildStatusLabel,
		canCancelActiveBuildStatus,
		engineRunKindLabel,
		engineRunStatusFilterValue,
		engineRunStatusToActiveBuildStatus,
		readEngineRunKind
	} from '$lib/types/build-stream';
	import { engineRunBuildDetail } from '$lib/utils/engine-run-build-detail';
	import { BuildsStore } from '$lib/stores/builds.svelte';
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
	import { useNamespace } from '$lib/stores/namespace.svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import { css, spinner, button, emptyText, input } from '$lib/styles/panda';

	interface Props {
		compact?: boolean;
		searchQuery?: string;
		embedded?: boolean;
	}

	type CancelTarget = {
		id: string;
	};

	type BuildPayloadData = {
		requestJson: Record<string, unknown> | null;
		resultJson: Record<string, unknown> | null;
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
	let expandedPayload = $state<BuildPayloadData | null>(null);
	let sortColumn = $state<string>('created_at');
	let sortDir = $state<'asc' | 'desc'>('desc');
	let syncingExpandedId: string | null = null;
	const detailStores = new SvelteMap<string, BuildStreamStore>();
	const detailSnapshots = new SvelteMap<string, ActiveBuildDetail>();
	const detailPayloads = new SvelteMap<string, BuildPayloadData>();
	const pendingCancelled = new SvelteMap<string, CancelBuildResponse>();
	const limit = 50;

	const queryParams = $derived({
		analysis_id: (pageState.url.searchParams.get('analysis_id') ?? undefined) || undefined,
		datasource_id: (pageState.url.searchParams.get('datasource_id') ?? undefined) || undefined,
		kind: kindFilter || undefined,
		status: statusFilter === 'all' ? undefined : statusFilter,
		limit,
		offset: (page - 1) * limit
	});

	const buildsStore = new BuildsStore();
	const ns = useNamespace();

	$effect(() => {
		const params = queryParams;
		buildsStore.load(params);
		return () => buildsStore.close();
	});

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources-lookup', ns.value],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 60_000,
		enabled: !ns.switching
	}));

	const analysesQuery = createQuery(() => ({
		queryKey: ['analyses-lookup', ns.value],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 60_000,
		enabled: !ns.switching
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

	const engineRunParams = $derived<ListEngineRunsParams>({
		analysis_id: queryParams.analysis_id,
		datasource_id: queryParams.datasource_id,
		kind: kindFilter && kindFilter !== 'build' ? kindFilter : undefined,
		status: engineRunStatusFilterValue(statusFilter),
		limit,
		offset: (page - 1) * limit
	});

	const engineRunsQuery = createQuery(() => ({
		queryKey: ['monitoring-engine-runs', ns.value, engineRunParams],
		queryFn: async () => {
			const result = await listEngineRuns(engineRunParams);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 10_000,
		enabled: !ns.switching && kindFilter !== 'build'
	}));

	const monitoringEngineRuns = $derived(
		(engineRunsQuery.data ?? []).filter((run) => run.kind !== 'build')
	);

	const engineRunMap = $derived.by(() => {
		const map = new SvelteMap<string, EngineRun>();
		for (const run of monitoringEngineRuns) map.set(run.id, run);
		return map;
	});

	const engineRunSummaries = $derived(monitoringEngineRuns.map(engineRunSummary));
	const runs = $derived([...buildsStore.builds, ...engineRunSummaries]);

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
		let result = runs;

		if (effectiveSearch) {
			const q = effectiveSearch.toLowerCase();
			result = result.filter((run) => {
				const outputName = buildOutputName(run) ?? '';
				const currentTabName = buildCurrentTabName(run) ?? '';
				const datasourceId = buildDatasourceId(run);
				const datasourceName = buildDatasourceName(run) ?? dsNames.get(datasourceId) ?? '';
				return (
					run.build_id.toLowerCase().includes(q) ||
					datasourceId.toLowerCase().includes(q) ||
					run.analysis_id.toLowerCase().includes(q) ||
					datasourceName.toLowerCase().includes(q) ||
					run.analysis_name.toLowerCase().includes(q) ||
					(analysisNames.get(run.analysis_id) ?? '').toLowerCase().includes(q) ||
					outputName.toLowerCase().includes(q) ||
					currentTabName.toLowerCase().includes(q) ||
					(run.current_step ?? '').toLowerCase().includes(q)
				);
			});
		}

		if (dateFrom) {
			const from = new Date(dateFrom);
			result = result.filter((run) => new Date(run.started_at) >= from);
		}
		if (dateTo) {
			// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local Date for comparison, not reactive state
			const to = new Date(dateTo);
			to.setHours(23, 59, 59, 999);
			result = result.filter((run) => new Date(run.started_at) <= to);
		}

		if (branchFilter) {
			result = result.filter((run) => getRunBranch(run) === branchFilter);
		}

		return sortRuns(result);
	});

	const hasAnyBuildRows = $derived(filteredRuns.length > 0);

	function sortRuns(list: ActiveBuildSummary[]): ActiveBuildSummary[] {
		const dir = sortDir === 'asc' ? 1 : -1;
		return [...list].sort((a, b) => {
			if (sortColumn === 'created_at') {
				return dir * (new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
			}
			if (sortColumn === 'duration_ms') {
				return dir * (summaryDurationMs(a) - summaryDurationMs(b));
			}
			if (sortColumn === 'kind') {
				return dir * effectiveKind(a).localeCompare(effectiveKind(b));
			}
			if (sortColumn === 'status') {
				return dir * currentStatus(a).localeCompare(currentStatus(b));
			}
			if (sortColumn === 'datasource') {
				const left =
					buildDatasourceName(a) ?? dsNames.get(buildDatasourceId(a)) ?? buildDatasourceId(a);
				const right =
					buildDatasourceName(b) ?? dsNames.get(buildDatasourceId(b)) ?? buildDatasourceId(b);
				return dir * left.localeCompare(right);
			}
			if (sortColumn === 'analysis') {
				const left = analysisNames.get(a.analysis_id) ?? a.analysis_name;
				const right = analysisNames.get(b.analysis_id) ?? b.analysis_name;
				return dir * left.localeCompare(right);
			}
			if (sortColumn === 'output') {
				const left = buildOutputName(a) ?? '';
				const right = buildOutputName(b) ?? '';
				return dir * left.localeCompare(right);
			}
			return 0;
		});
	}

	function engineRunSummary(run: EngineRun): ActiveBuildSummary {
		const kind = readEngineRunKind(run.kind);
		return {
			build_id: run.id,
			analysis_id: run.analysis_id ?? run.id,
			analysis_name: run.analysis_id ?? run.id,
			namespace: '',
			status: engineRunStatusToActiveBuildStatus(run.status),
			started_at: run.created_at,
			starter: { user_id: null, display_name: null, email: null, triggered_by: run.triggered_by },
			resource_config: null,
			progress: run.progress,
			elapsed_ms: run.duration_ms ?? 0,
			estimated_remaining_ms: null,
			current_step: run.current_step,
			current_step_index: null,
			total_steps: 0,
			current_kind: kind,
			current_datasource_id: run.datasource_id,
			current_tab_id: null,
			current_tab_name: null,
			current_output_id: null,
			current_output_name: null,
			current_engine_run_id: run.id,
			total_tabs: 0,
			cancelled_at: null,
			cancelled_by: null,
			result_json: null
		};
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
		if (!id) return '-';
		return map.get(id) ?? `${id.slice(0, 8)}...`;
	}

	function effectiveKind(run: ActiveBuildSummary): string {
		return run.current_kind ?? '';
	}

	function buildDatasourceId(run: ActiveBuildSummary): string {
		return run.current_datasource_id ?? run.current_output_id ?? '';
	}

	function buildDatasourceName(run: ActiveBuildSummary): string | null {
		const datasourceId = buildDatasourceId(run);
		if (!datasourceId) return null;
		return dsNames.get(datasourceId) ?? null;
	}

	function buildCurrentTabName(run: ActiveBuildSummary): string | null {
		return run.current_tab_name ?? null;
	}

	function buildOutputName(run: ActiveBuildSummary): string | null {
		return run.current_output_name ?? null;
	}

	function getRunBranch(run: ActiveBuildSummary): string | null {
		const payload = detailPayloads.get(run.build_id)?.requestJson;
		if (!payload) return null;
		const opts = payload.iceberg_options as Record<string, unknown> | undefined;
		if (typeof opts?.branch === 'string' && opts.branch.trim()) return opts.branch;

		const datasource = payload.datasource_config as Record<string, unknown> | undefined;
		if (typeof datasource?.branch === 'string' && datasource.branch.trim()) {
			return datasource.branch;
		}

		const result = detailPayloads.get(run.build_id)?.resultJson;
		const meta = result?.metadata as Record<string, unknown> | undefined;
		if (typeof meta?.branch === 'string' && meta.branch.trim()) return meta.branch;
		return null;
	}

	function summaryDurationMs(run: ActiveBuildSummary): number {
		const cancelled = pendingCancelled.get(run.build_id);
		if (cancelled?.duration_ms !== null && cancelled?.duration_ms !== undefined) {
			return cancelled.duration_ms;
		}
		return run.elapsed_ms ?? 0;
	}

	function currentStatus(
		run: ActiveBuildSummary
	): 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' {
		if (pendingCancelled.has(run.build_id)) return 'cancelled';
		return run.status;
	}

	function cancelledAt(run: ActiveBuildSummary): string | null {
		return pendingCancelled.get(run.build_id)?.cancelled_at ?? run.cancelled_at ?? null;
	}

	function cancelledBy(run: ActiveBuildSummary): string | null {
		return pendingCancelled.get(run.build_id)?.cancelled_by ?? run.cancelled_by ?? null;
	}

	function lastCompletedStep(run: ActiveBuildSummary): string | null {
		const detail = detailSnapshots.get(run.build_id);
		if (!detail) return null;
		for (let index = detail.steps.length - 1; index >= 0; index -= 1) {
			if (detail.steps[index].state === 'completed') return detail.steps[index].step_name;
		}
		return null;
	}

	function canCancelRun(run: ActiveBuildSummary): boolean {
		return canCancelActiveBuildStatus(currentStatus(run));
	}

	function requestCancelRun(run: ActiveBuildSummary): void {
		if (!canCancelRun(run) || cancelPending) return;
		cancelError = null;
		cancelTarget = { id: run.build_id };
	}

	function closeCancelDialog(): void {
		if (cancelPending) return;
		cancelTarget = null;
	}

	function updateCancelledRun(buildId: string, cancelled: CancelBuildResponse): void {
		pendingCancelled.set(buildId, cancelled);
		const current = runs.find((run) => run.build_id === buildId);
		if (!current) return;
		buildsStore.replaceBuild({
			...current,
			status: 'cancelled',
			cancelled_at: cancelled.cancelled_at,
			cancelled_by: cancelled.cancelled_by,
			elapsed_ms: cancelled.duration_ms ?? current.elapsed_ms
		});
	}

	$effect(() => {
		for (const [buildId] of pendingCancelled) {
			const run = runs.find((item) => item.build_id === buildId);
			if (!run) {
				pendingCancelled.delete(buildId);
				continue;
			}
			if (!canCancelActiveBuildStatus(run.status)) {
				pendingCancelled.delete(buildId);
			}
		}
	});

	async function confirmCancelRun(): Promise<void> {
		const target = cancelTarget;
		if (!target || cancelPending) return;
		cancelTarget = null;
		cancelPending = true;
		cancelError = null;
		const result = await cancelBuild(target.id);
		result.match(
			(cancelled) => {
				updateCancelledRun(target.id, cancelled);
				buildsStore.refresh();
			},
			(err) => {
				cancelError = err.message;
			}
		);
		cancelPending = false;
	}

	async function refreshHistory(): Promise<void> {
		buildsStore.refresh();
	}

	function detailStore(buildId: string): BuildStreamStore {
		let store = detailStores.get(buildId);
		if (!store) {
			store = new BuildStreamStore();
			detailStores.set(buildId, store);
		}
		return store;
	}

	function summaryDetail(run: ActiveBuildSummary): ActiveBuildDetail {
		return {
			...run,
			steps: [],
			query_plans: [],
			latest_resources: null,
			resources: [],
			logs: [],
			results: [],
			duration_ms: run.elapsed_ms,
			error: null,
			request_json: null,
			result_json: null
		};
	}

	function replaceRun(next: ActiveBuildSummary): void {
		buildsStore.replaceBuild(next);
	}

	function setDetailPayload(build: ActiveBuildDetail): void {
		detailSnapshots.set(build.build_id, build);
		detailPayloads.set(build.build_id, {
			requestJson: (build.request_json as Record<string, unknown> | null) ?? null,
			resultJson: (build.result_json as Record<string, unknown> | null) ?? null
		});
		if (expandedId === build.build_id) {
			expandedPayload = detailPayloads.get(build.build_id) ?? null;
		}
	}

	async function syncExpandedRun(buildId: string): Promise<void> {
		const run = runs.find((item) => item.build_id === buildId);
		if (!run || syncingExpandedId === buildId) return;
		const engineRun = engineRunMap.get(buildId);
		if (engineRun) {
			const store = detailStore(buildId);
			store.close();
			store.applySnapshot(summaryDetail(run));
			expandedStore = store;
			expandedPayload = null;
			expandedLiveId = null;
			await tick();
			if (expandedId !== buildId) return;
			const engineRunDetail = engineRunBuildDetail(engineRun);
			store.applySnapshot(engineRunDetail);
			detailSnapshots.set(buildId, engineRunDetail);
			detailPayloads.set(buildId, {
				requestJson: engineRunDetail.request_json,
				resultJson: engineRunDetail.result_json
			});
			expandedPayload = detailPayloads.get(buildId) ?? null;
			return;
		}
		const cached = detailSnapshots.get(buildId);
		if (cached && run.status !== 'queued' && run.status !== 'running') {
			expandedStore = detailStore(buildId);
			expandedPayload = detailPayloads.get(buildId) ?? null;
			return;
		}
		const store = detailStore(buildId);
		if (!cached) {
			store.close();
			store.applySnapshot(summaryDetail(run));
			expandedStore = store;
			expandedPayload = null;
		}
		syncingExpandedId = buildId;
		const detail = await getBuild(buildId).match(
			(response: ActiveBuildDetail) => response,
			() => null
		);
		if (syncingExpandedId === buildId) syncingExpandedId = null;
		if (expandedId !== buildId || !detail) return;
		replaceRun(detail);
		setDetailPayload(detail);
		if (canCancelActiveBuildStatus(detail.status)) {
			store.watch(detail.build_id);
			store.applySnapshot(detail);
			expandedLiveId = detail.build_id;
		} else {
			store.close();
			store.applySnapshot(detail);
			expandedLiveId = null;
		}
		expandedStore = store;
	}

	$effect(() => {
		for (const [buildId, store] of detailStores) {
			if (buildId === expandedId) continue;
			store.close();
		}
		const expandedRun = runs.find((run) => run.build_id === expandedId) ?? null;
		if (!expandedRun) {
			expandedLiveId = null;
			expandedStore = null;
			expandedPayload = null;
			return;
		}
		void syncExpandedRun(expandedRun.build_id);
	});

	$effect(() => {
		const liveId = expandedLiveId;
		const store = expandedStore;
		if (!liveId || !store || !store.done) return;
		expandedLiveId = null;
		void getBuild(liveId).match(
			(persisted) => {
				if (expandedId !== liveId) return;
				store.close();
				setDetailPayload(persisted);
				replaceRun(persisted);
				store.applySnapshot(persisted);
				expandedStore = store;
			},
			(err) => {
				console.warn('Failed to fetch persisted build after build done:', err.message);
			}
		);
	});

	$effect(() => {
		const liveId = expandedLiveId;
		const store = expandedStore;
		if (!liveId || !store || store.status !== 'disconnected' || store.done) return;
		expandedLiveId = null;
		void getBuild(liveId).match(
			(persisted) => {
				if (expandedId !== liveId) return;
				store.close();
				setDetailPayload(persisted);
				replaceRun(persisted);
				store.applySnapshot(persisted);
				expandedStore = store;
			},
			(err) => {
				console.warn('Failed to fetch persisted build after WS disconnect:', err.message);
			}
		);
	});

	$effect(() => {
		const target = cancelTarget;
		if (!target) return;
		const latest = runs.find((run) => run.build_id === target.id);
		if (!latest || (latest.status !== 'queued' && latest.status !== 'running')) {
			cancelTarget = null;
			cancelPending = false;
		}
	});

	$effect(() => {
		return () => {
			for (const store of detailStores.values()) {
				store.close();
			}
			detailStores.clear();
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
				Build history for previews and exports
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
				<option value="build">Build</option>
				<option value="preview">Preview</option>
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

	{#if buildsStore.status === 'connecting'}
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
	{:else if buildsStore.status === 'error'}
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
			{buildsStore.error ?? 'Failed to load builds'}
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
					{#each filteredRuns as run (run.build_id)}
						<tr
							data-build-row={run.build_id}
							data-build-source="history"
							data-build-status={currentStatus(run)}
							data-build-kind={effectiveKind(run)}
							data-build-datasource-id={buildDatasourceId(run)}
							data-build-datasource-name={buildDatasourceName(run) ??
								resolveName(buildDatasourceId(run), dsNames)}
							data-build-analysis-id={run.analysis_id}
							data-build-analysis-name={resolveName(run.analysis_id, analysisNames)}
							data-build-output-name={buildOutputName(run) ?? ''}
							class={css(
								{
									cursor: 'pointer',
									_hover: { backgroundColor: 'bg.hover' }
								},
								expandedId === run.build_id && { backgroundColor: 'bg.secondary' }
							)}
							onclick={() => toggleExpand(run.build_id)}
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
									class={expandedId === run.build_id
										? undefined
										: css({ transform: 'rotate(-90deg)' })}
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
									{#if effectiveKind(run) === 'build'}
										<Database size={14} class={css({ color: 'accent.primary' })} />
										<span>{engineRunKindLabel(effectiveKind(run))}</span>
									{:else if effectiveKind(run) === 'download'}
										<Download size={14} class={css({ color: 'fg.success' })} />
										<span>{engineRunKindLabel(effectiveKind(run))}</span>
									{:else if effectiveKind(run) === 'row_count'}
										<Hash size={14} class={css({ color: 'fg.muted' })} />
										<span>{engineRunKindLabel(effectiveKind(run))}</span>
									{:else}
										<Database size={14} class={css({ color: 'fg.muted' })} />
										<span>{engineRunKindLabel(effectiveKind(run))}</span>
									{/if}
									{#if run.starter.triggered_by === 'schedule'}
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
										{#if currentStatus(run) === 'queued'}
											<Loader
												size={14}
												class={css({
													color: 'fg.secondary',
													animation: 'spin 1s linear infinite'
												})}
											/>
											<span class={css({ color: 'fg.secondary' })}
												>{activeBuildStatusLabel(currentStatus(run))}</span
											>
										{:else if currentStatus(run) === 'running'}
											<Loader
												size={14}
												class={css({
													color: 'accent.primary',
													animation: 'spin 1s linear infinite'
												})}
											/>
											<span class={css({ color: 'accent.primary' })}
												>{activeBuildStatusLabel(currentStatus(run))}</span
											>
										{:else if currentStatus(run) === 'completed'}
											<CircleCheck size={14} class={css({ color: 'fg.success' })} />
											<span class={css({ color: 'fg.success' })}
												>{activeBuildStatusLabel(currentStatus(run))}</span
											>
										{:else if currentStatus(run) === 'cancelled'}
											<CircleX size={14} class={css({ color: 'fg.warning' })} />
											<span class={css({ color: 'fg.warning' })}
												>{activeBuildStatusLabel(currentStatus(run))}</span
											>
										{:else}
											<CircleX size={14} class={css({ color: 'fg.error' })} />
											<span class={css({ color: 'fg.error' })}
												>{activeBuildStatusLabel(currentStatus(run))}</span
											>
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
											data-testid={`build-row-cancel-${run.build_id}`}
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
									title={buildDatasourceId(run)}
								>
									{buildDatasourceName(run) ?? resolveName(buildDatasourceId(run), dsNames)}
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
								{#if buildOutputName(run)}
									<span
										class={css({
											display: 'block',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											fontSize: 'xs',
											color: 'fg.secondary'
										})}
										title={buildOutputName(run) ?? ''}
									>
										{buildOutputName(run)}
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
								{formatDuration(summaryDurationMs(run))}
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
								{formatDate(run.started_at)}
							</td>
						</tr>
						{#if expandedId === run.build_id}
							<tr data-build-detail={run.build_id}>
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
												<strong>Build ID:</strong>
												{run.build_id}
											</span>
											{#if run.current_engine_run_id}
												<span class={css({ color: 'fg.secondary' })}>
													<strong>Engine Run ID:</strong>
													{run.current_engine_run_id}
												</span>
											{/if}
											{#if currentStatus(run) === 'cancelled'}
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
												title={engineRunKindLabel(run.current_kind ?? '')}
												requestJson={expandedPayload?.requestJson ?? null}
												resultJson={expandedPayload?.resultJson ?? null}
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
