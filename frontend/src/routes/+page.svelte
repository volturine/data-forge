<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { PersistedState } from 'runed';
	import { SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { listAnalyses, deleteAnalysis } from '$lib/api/analysis';
	import GalleryGrid from '$lib/components/gallery/GalleryGrid.svelte';
	import EmptyState from '$lib/components/gallery/EmptyState.svelte';
	import AnalysisFilters from '$lib/components/gallery/AnalysisFilters.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { Plus, Trash2, X } from 'lucide-svelte';
	import type { SortOption } from '$lib/components/gallery/AnalysisFilters.svelte';
	import { toEpochDisplay } from '$lib/utils/datetime';

	const queryClient = useQueryClient();

	const query = createQuery(() => ({
		queryKey: ['analyses'],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		}
	}));

	const searchQuery = new PersistedState('analysis-search', '');
	const sortOption = new PersistedState<SortOption>('analysis-sort', 'newest');

	// Selection state
	const selectedIds = new SvelteSet<string>();
	let deleteConfirmId = $state<string | null>(null);
	let bulkDeleteConfirm = $state(false);

	const filteredAndSortedAnalyses = $derived.by(() => {
		if (!query.data) return [];

		let result = [...query.data];

		if (searchQuery.current) {
			const lowerQuery = searchQuery.current.toLowerCase();
			result = result.filter((analysis) => analysis.name.toLowerCase().includes(lowerQuery));
		}

		result.sort((a, b) => {
			const left = toEpochDisplay(a.updated_at);
			const right = toEpochDisplay(b.updated_at);
			switch (sortOption.current) {
				case 'newest':
					return right - left;
				case 'oldest':
					return left - right;
				case 'name-asc':
					return a.name.localeCompare(b.name);
				case 'name-desc':
					return b.name.localeCompare(a.name);
				default:
					return 0;
			}
		});

		return result;
	});

	const selectionCount = $derived(selectedIds.size);
	function createNew() {
		goto(resolve('/analysis/new'), { invalidateAll: true });
	}

	function handleSearch(query: string) {
		searchQuery.current = query;
	}

	function handleSort(option: SortOption) {
		sortOption.current = option;
	}

	function toggleSelect(id: string) {
		if (selectedIds.has(id)) {
			selectedIds.delete(id);
			return;
		}
		selectedIds.add(id);
	}

	function selectAll() {
		const ids = filteredAndSortedAnalyses.map((a) => a.id);
		selectedIds.clear();
		for (const id of ids) {
			selectedIds.add(id);
		}
	}

	function clearSelection() {
		selectedIds.clear();
	}

	function requestDelete(id: string) {
		deleteConfirmId = id;
	}

	function confirmDelete() {
		if (!deleteConfirmId) return;

		deleteAnalysis(deleteConfirmId).match(
			() => {
				queryClient.invalidateQueries({ queryKey: ['analyses'] });
				if (deleteConfirmId) {
					selectedIds.delete(deleteConfirmId);
				}
				deleteConfirmId = null;
			},
			(error) => {
				alert(`Failed to delete: ${error.message}`);
				deleteConfirmId = null;
			}
		);
	}

	function cancelDelete() {
		deleteConfirmId = null;
	}

	function requestBulkDelete() {
		bulkDeleteConfirm = true;
	}

	async function confirmBulkDelete() {
		const idsToDelete = Array.from(selectedIds);
		let failed = 0;

		for (const id of idsToDelete) {
			const result = await deleteAnalysis(id);
			if (result.isErr()) failed++;
		}

		queryClient.invalidateQueries({ queryKey: ['analyses'] });
		selectedIds.clear();
		bulkDeleteConfirm = false;

		if (failed > 0) {
			alert(`Failed to delete ${failed} analysis${failed > 1 ? 'es' : ''}.`);
		}
	}

	function cancelBulkDelete() {
		bulkDeleteConfirm = false;
	}

	const deleteConfirmName = $derived.by(() => {
		if (!deleteConfirmId || !query.data) return '';
		const analysis = query.data.find((a) => a.id === deleteConfirmId);
		return analysis?.name ?? '';
	});
</script>

<div class="mx-auto box-border min-h-full max-w-[1200px] px-6 py-7 md:px-4 md:py-4">
	<header
		class="mb-8 flex flex-col items-stretch justify-between gap-6 border-b border-primary pb-6 md:flex-row md:items-start"
	>
		<div>
			<h1 class="m-0 mb-2 text-2xl font-semibold">Analyses</h1>
			<p class="m-0 text-sm text-fg-tertiary">Browse and manage your data analyses</p>
		</div>
		<button class="btn-primary w-full justify-center md:w-auto" onclick={createNew}>
			<Plus size={16} />
			New Analysis
		</button>
	</header>

	<main>
		{#if query.isPending}
			<div class="py-4">
				<div class="grid grid-cols-1 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
					{#each Array(6) as _, i (i)}
						<div class="bg-primary overflow-hidden rounded-sm border border-primary">
							<div class="aspect-video w-full animate-shimmer shimmer-bg"></div>
							<div class="p-4">
								<div class="mb-3 h-4 w-[70%] animate-shimmer shimmer-bg rounded-sm"></div>
								<div class="mb-3 h-3.5 animate-shimmer shimmer-bg rounded-sm"></div>
								<div class="h-3.5 w-1/2 animate-shimmer shimmer-bg rounded-sm"></div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{:else if query.isError}
			<div
				class="error-box flex min-h-[400px] flex-col items-center justify-center px-6 py-12 text-center"
			>
				<div class="mb-6 flex h-12 w-12 items-center justify-center rounded-sm text-xl font-bold">
					!
				</div>
				<h2 class="m-0 mb-2 text-lg font-semibold">Failed to load analyses</h2>
				<p class="m-0 mb-6 max-w-[400px] text-sm">{query.error.message}</p>
				<button class="btn-primary" onclick={() => query.refetch()}>Try again</button>
			</div>
		{:else if query.data}
			{#if query.data.length === 0}
				<EmptyState />
			{:else}
				<AnalysisFilters
					searchQuery={searchQuery.current}
					sortOption={sortOption.current}
					onSearch={handleSearch}
					onSort={handleSort}
				/>
				{#if selectionCount > 0}
					<div
						class="bg-secondary mb-4 flex items-center justify-between rounded-sm border border-primary px-4 py-3"
					>
						<span class="text-fg-primary text-sm font-medium">{selectionCount} selected</span>
						<div class="flex items-center gap-2">
							<button
								class="btn-text flex items-center gap-1 rounded-sm border border-transparent bg-transparent px-3 py-2 text-sm transition-all"
								onclick={selectAll}
							>
								Select All
							</button>
							<button
								class="btn-text flex items-center gap-1 rounded-sm border border-transparent bg-transparent px-3 py-2 text-sm transition-all"
								onclick={clearSelection}
							>
								<X size={14} />
								Clear
							</button>
							<button class="btn-danger flex items-center gap-1" onclick={requestBulkDelete}>
								<Trash2 size={14} />
								Delete
							</button>
						</div>
					</div>
				{/if}
				{#if filteredAndSortedAnalyses.length === 0}
					<div class="rounded-sm border border-dashed border-primary px-6 py-12 text-center">
						<p class="text-fg-tertiary m-0 text-sm">No analyses match your search.</p>
					</div>
				{:else}
					<GalleryGrid
						analyses={filteredAndSortedAnalyses}
						{selectedIds}
						onDelete={requestDelete}
						onToggleSelect={toggleSelect}
					/>
				{/if}
			{/if}
		{/if}
	</main>
</div>

<ConfirmDialog
	show={deleteConfirmId !== null}
	title="Delete Analysis"
	message={deleteConfirmName
		? `Are you sure you want to delete "${deleteConfirmName}"? This action cannot be undone.`
		: 'Are you sure you want to delete this analysis? This action cannot be undone.'}
	confirmText="Delete"
	cancelText="Cancel"
	onConfirm={confirmDelete}
	onCancel={cancelDelete}
/>

<ConfirmDialog
	show={bulkDeleteConfirm}
	title="Delete Analyses"
	message={`Are you sure you want to delete ${selectionCount} analysis${selectionCount > 1 ? 'es' : ''}? This action cannot be undone.`}
	confirmText="Delete"
	cancelText="Cancel"
	onConfirm={confirmBulkDelete}
	onCancel={cancelBulkDelete}
/>

<style>
	.shimmer-bg {
		background: linear-gradient(
			90deg,
			var(--bg-tertiary) 25%,
			var(--bg-hover) 50%,
			var(--bg-tertiary) 75%
		);
		background-size: 200% 100%;
	}

	@keyframes shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}

	.animate-shimmer {
		animation: shimmer 1.5s infinite;
	}

	.btn-text {
		color: var(--fg-secondary);
	}

	.btn-text:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
</style>
