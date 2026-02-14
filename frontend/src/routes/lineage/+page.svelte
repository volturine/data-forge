<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { getLineage, type LineageNode, type LineageResponse } from '$lib/api/lineage';
	import LineageGraph from '$lib/components/common/LineageGraph.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import { Loader, X, Database, BarChart3 } from 'lucide-svelte';

	const query = createQuery(() => ({
		queryKey: ['lineage'],
		queryFn: async () => {
			const result = await getLineage();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const emptyLineage: LineageResponse = { nodes: [], edges: [] };
	const lineage = $derived(query.data ?? emptyLineage);

	let selectedNode = $state<LineageNode | null>(null);
	let pageEl = $state<HTMLDivElement | undefined>(undefined);

	// Compute fixed position from the page element's bounding rect
	// $effect needed: reads DOM bounding rect which $derived cannot access
	let panelTop = $state(0);
	let panelLeft = $state(0);
	$effect(() => {
		if (!pageEl || !selectedNode) return;
		const rect = pageEl.getBoundingClientRect();
		// Position below the header (header is ~49px: py-3 + text + border)
		panelTop = rect.top + 49;
		panelLeft = rect.left;
	});

	function handleNodeClick(node: LineageNode) {
		if (selectedNode?.id === node.id) {
			selectedNode = null;
			return;
		}
		selectedNode = node;
	}

	function closePanel() {
		selectedNode = null;
	}

	// Parse raw ID from prefixed node ID ("datasource:uuid" or "analysis:uuid")
	const selectedRawId = $derived(
		selectedNode ? selectedNode.id.split(':').slice(1).join(':') : null
	);
	const selectedType = $derived(selectedNode?.type ?? null);
</script>

<div class="flex h-full flex-col" bind:this={pageEl}>
	<header class="border-b border-tertiary bg-bg-primary px-6 py-3">
		<h1 class="m-0 text-lg">Data Lineage</h1>
	</header>

	<div class="min-h-0 flex-1">
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
			<LineageGraph {lineage} onnodeclick={handleNodeClick} />
		{/if}
	</div>
</div>

<!-- Slide panel: rendered outside graph DOM to avoid transform stacking context conflicts -->
{#if selectedNode}
	<div
		class="fixed z-[9999] flex w-96 flex-col border-r border-tertiary bg-bg-primary shadow-lg"
		style="top: {panelTop}px; left: {panelLeft}px; bottom: 0;"
	>
		<div class="flex items-center gap-3 border-b border-tertiary px-4 py-3">
			<div class="flex items-center gap-2 text-fg-muted">
				{#if selectedType === 'datasource'}
					<Database size={16} />
				{:else}
					<BarChart3 size={16} />
				{/if}
			</div>
			<div class="min-w-0 flex-1">
				<div class="text-xs uppercase tracking-wide text-fg-muted">
					{selectedType === 'datasource' ? 'Datasource' : 'Analysis'}
				</div>
				<div class="truncate text-sm font-semibold text-fg-primary">
					{selectedNode.name}
				</div>
			</div>
			<button
				class="btn-ghost btn-sm p-1"
				onclick={closePanel}
				title="Close panel"
				aria-label="Close panel"
			>
				<X size={14} />
			</button>
		</div>

		<div class="flex-1 overflow-y-auto p-4">
			<!-- Node details -->
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

			<!-- Schedules for datasource nodes -->
			{#if selectedType === 'datasource' && selectedRawId}
				<div class="border-t border-tertiary pt-4">
					<h3 class="mb-3 text-sm font-semibold text-fg-primary">Schedules</h3>
					<ScheduleManager datasourceId={selectedRawId} compact />
				</div>
			{/if}
		</div>
	</div>
{/if}
