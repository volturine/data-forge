<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { getLineage, type LineageNode, type LineageResponse } from '$lib/api/lineage';
	import { listDatasources } from '$lib/api/datasource';
	import LineageGraph from '$lib/components/common/LineageGraph.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import {
		Loader,
		X,
		Database,
		BarChart3,
		ArrowRight,
		ArrowDown,
		LayoutGrid,
		RotateCcw,
		ZoomIn,
		ZoomOut
	} from 'lucide-svelte';

	type LayoutMode = 'horizontal' | 'vertical' | 'grid';
	type LineageGraphApi = {
		resetLineageView: () => void;
		zoomInView: () => void;
		zoomOutView: () => void;
	};

	let selectedDatasourceId = $state<string>('');
	let selectedBranch = $state<string>('');

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: async () => {
			const result = await listDatasources(true);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const outputDatasources = $derived.by(() =>
		(datasourcesQuery.data ?? []).filter((ds) => ds.created_by === 'analysis')
	);

	const branchOptions = $derived.by(() => {
		const selected = outputDatasources.find((ds) => ds.id === selectedDatasourceId);
		const config = (selected?.config ?? {}) as Record<string, unknown>;
		const branches = config.branches as string[] | undefined;
		if (!branches || branches.length === 0) return ['master'];
		return branches;
	});

	// Subscription: $derived can't sync branch selection.
	$effect(() => {
		if (!selectedDatasourceId) {
			selectedBranch = '';
			return;
		}
		if (!selectedBranch && branchOptions.length > 0) {
			selectedBranch = branchOptions[0] ?? '';
		}
	});

	const query = createQuery(() => ({
		queryKey: ['lineage', selectedDatasourceId, selectedBranch],
		queryFn: async () => {
			const result = await getLineage(selectedDatasourceId || null, selectedBranch || null);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const emptyLineage: LineageResponse = { nodes: [], edges: [] };
	const lineage = $derived(query.data ?? emptyLineage);

	let selectedNode = $state<LineageNode | null>(null);
	const panelWidth = 384;
	let layoutMode = $state<LayoutMode>('horizontal');
	let zoomPercent = $state(100);
	let graphRef = $state<LineageGraphApi | null>(null);

	function closePanel() {
		selectedNode = null;
	}

	// Parse raw ID from prefixed node ID ("datasource:uuid" or "analysis:uuid")
	const selectedRawId = $derived(
		selectedNode ? selectedNode.id.split(':').slice(1).join(':') : null
	);
	const selectedType = $derived(selectedNode?.type ?? null);

	function setLayout(mode: LayoutMode) {
		layoutMode = mode;
	}

	function zoomIn() {
		graphRef?.zoomInView();
	}

	function zoomOut() {
		graphRef?.zoomOutView();
	}

	function resetView() {
		graphRef?.resetLineageView();
	}

	function handleDatasourceChange(event: Event) {
		const target = event.currentTarget as HTMLSelectElement;
		selectedDatasourceId = target.value;
		selectedBranch = '';
	}

	function handleBranchChange(event: Event) {
		const target = event.currentTarget as HTMLSelectElement;
		selectedBranch = target.value;
	}
</script>

<div class="flex h-full flex-col">
	<header class="border-b border-tertiary bg-bg-primary px-6 py-3">
		<h1 class="m-0 text-lg">Data Lineage</h1>
	</header>

	<div class="lineage-page">
		<div class="lineage-toolbar-row">
			<div class="flex items-center gap-2">
				<select
					class="text-xs border border-tertiary bg-bg-primary px-2 py-1"
					value={selectedDatasourceId}
					onchange={handleDatasourceChange}
				>
					<option value="">Select output datasource</option>
					{#each outputDatasources as ds (ds.id)}
						<option value={ds.id}>{ds.name}</option>
					{/each}
				</select>
				<select
					class="text-xs border border-tertiary bg-bg-primary px-2 py-1"
					value={selectedBranch}
					onchange={handleBranchChange}
					disabled={!selectedDatasourceId}
				>
					{#if !selectedDatasourceId}
						<option value="">Select branch</option>
					{:else}
						{#each branchOptions as branch (branch)}
							<option value={branch}>{branch}</option>
						{/each}
					{/if}
				</select>
			</div>
			<span class="mr-2 text-xs text-fg-muted">Layout</span>
			<button
				class="btn-sm {layoutMode === 'horizontal' ? 'btn-primary' : 'btn-ghost'}"
				onclick={() => setLayout('horizontal')}
				title="Horizontal tree layout"
			>
				<ArrowRight size={14} />
				<span class="text-xs">Horizontal</span>
			</button>
			<button
				class="btn-sm {layoutMode === 'vertical' ? 'btn-primary' : 'btn-ghost'}"
				onclick={() => setLayout('vertical')}
				title="Vertical tree layout"
			>
				<ArrowDown size={14} />
				<span class="text-xs">Vertical</span>
			</button>
			<button
				class="btn-sm {layoutMode === 'grid' ? 'btn-primary' : 'btn-ghost'}"
				onclick={() => setLayout('grid')}
				title="Grid layout"
			>
				<LayoutGrid size={14} />
				<span class="text-xs">Grid</span>
			</button>

			<div class="mx-2 h-4 w-px bg-border-primary"></div>

			<button class="btn-sm btn-ghost" onclick={zoomIn} title="Zoom in">
				<ZoomIn size={14} />
			</button>
			<button class="btn-sm btn-ghost" onclick={zoomOut} title="Zoom out">
				<ZoomOut size={14} />
			</button>
			<button class="btn-sm btn-ghost" onclick={resetView} title="Reset view">
				<RotateCcw size={14} />
			</button>

			<span class="ml-auto text-xs text-fg-muted">{zoomPercent}%</span>
		</div>

		<aside class="lineage-panel">
			<div class="flex items-center gap-3 border-b border-tertiary px-4 py-3">
				{#if selectedNode}
					<div class="flex items-center gap-2 text-fg-muted">
						{#if selectedType === 'datasource'}
							<Database size={16} />
						{:else}
							<BarChart3 size={16} />
						{/if}
					</div>
				{/if}
				<div class="min-w-0 flex-1">
					<div class="text-xs uppercase tracking-wide text-fg-muted">
						{selectedNode ? (selectedType === 'datasource' ? 'Datasource' : 'Analysis') : 'Details'}
					</div>
					<div class="truncate text-sm font-semibold text-fg-primary">
						{selectedNode ? selectedNode.name : 'Select a node'}
					</div>
				</div>
				{#if selectedNode}
					<button
						class="btn-ghost btn-sm p-1"
						onclick={closePanel}
						title="Close panel"
						aria-label="Close panel"
					>
						<X size={14} />
					</button>
				{/if}
			</div>

			<div class="flex-1 overflow-y-auto p-4">
				{#if selectedNode}
					<div class="mb-4 space-y-2">
						{#if selectedNode.source_type}
							<div class="flex items-center justify-between text-sm">
								<span class="text-fg-muted">Source</span>
								<span class="text-fg-primary">{selectedNode.source_type}</span>
							</div>
						{/if}
						{#if selectedNode.status}
							<div class="flex items-center justify-between text-sm">
								<span class="text-fg-muted">Status</span>
								<span class="text-fg-primary">{selectedNode.status}</span>
							</div>
						{/if}
						<div class="flex items-center justify-between text-sm">
							<span class="text-fg-muted">ID</span>
							<span class="truncate pl-4 text-xs text-fg-tertiary">{selectedRawId}</span>
						</div>
					</div>

					{#if selectedType === 'datasource' && selectedRawId}
						<div class="border-t border-tertiary pt-4">
							<h3 class="mb-3 text-sm font-semibold text-fg-primary">Schedules</h3>
							<ScheduleManager datasourceId={selectedRawId} compact />
						</div>
					{/if}
				{:else}
					<p class="text-sm text-fg-tertiary">Click a node to view details and schedules.</p>
				{/if}
			</div>
		</aside>

		<div class="lineage-canvas">
			{#if query.isLoading}
				<div class="flex h-full items-center justify-center gap-2 text-fg-tertiary">
					<Loader size={16} class="spin" />
					Loading lineage...
				</div>
			{:else if query.isError}
				<div class="flex h-full items-center justify-center">
					<p class="text-sm text-error-fg">Failed to load lineage.</p>
				</div>
			{:else}
				<LineageGraph
					bind:this={graphRef}
					{lineage}
					showToolbar={false}
					bind:layoutMode
					bind:zoomPercent
					onnodeclick={(node) => {
						selectedNode = node;
					}}
					panelOffset={panelWidth}
				/>
			{/if}
		</div>
	</div>
</div>
