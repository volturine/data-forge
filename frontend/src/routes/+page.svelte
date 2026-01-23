<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { PersistedState } from 'runed';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { listAnalyses, deleteAnalysis } from '$lib/api/analysis';
	import GalleryGrid from '$lib/components/gallery/GalleryGrid.svelte';
	import EmptyState from '$lib/components/gallery/EmptyState.svelte';
	import AnalysisFilters from '$lib/components/gallery/AnalysisFilters.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { Plus } from 'lucide-svelte';
	import type { SortOption } from '$lib/components/gallery/AnalysisFilters.svelte';

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
	let deleteConfirmId = $state<string | null>(null);

	const filteredAndSortedAnalyses = $derived.by(() => {
		if (!query.data) return [];

		let result = [...query.data];

		if (searchQuery.current) {
			const lowerQuery = searchQuery.current.toLowerCase();
			result = result.filter((analysis) => analysis.name.toLowerCase().includes(lowerQuery));
		}

		result.sort((a, b) => {
			switch (sortOption.current) {
				case 'newest':
					return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
				case 'oldest':
					return new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
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

	function createNew() {
		goto(resolve('/analysis/new'), { invalidateAll: true });
	}

	function handleSearch(query: string) {
		searchQuery.current = query;
	}

	function handleSort(option: SortOption) {
		sortOption.current = option;
	}

	function requestDelete(id: string) {
		deleteConfirmId = id;
	}

	function confirmDelete() {
		if (!deleteConfirmId) return;

		deleteAnalysis(deleteConfirmId).match(
			() => {
				queryClient.invalidateQueries({ queryKey: ['analyses'] });
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
</script>

<div class="container">
	<header class="page-header">
		<div class="header-text">
			<h1>Analyses</h1>
			<p class="subtitle">Browse and manage your data analyses</p>
		</div>
		<button class="btn-primary btn-new" onclick={createNew}>
			<Plus size={16} />
			New Analysis
		</button>
	</header>

	<main>
		{#if query.isPending}
			<div class="loading">
				<div class="skeleton-grid">
					{#each Array(6) as _, i (i)}
						<div class="skeleton-card">
							<div class="skeleton-thumbnail"></div>
							<div class="skeleton-content">
								<div class="skeleton-title"></div>
								<div class="skeleton-text"></div>
								<div class="skeleton-text small"></div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{:else if query.isError}
			<div class="error-box error-state">
				<div class="error-icon">!</div>
				<h2>Failed to load analyses</h2>
				<p>{query.error.message}</p>
				<button class="btn-primary" onclick={() => query.refetch()}>Try again</button>
			</div>
		{:else if query.data}
			{#if query.data.length === 0}
				<EmptyState />
			{:else}
				<AnalysisFilters onSearch={handleSearch} onSort={handleSort} />
				{#if filteredAndSortedAnalyses.length === 0}
					<div class="no-results">
						<p>No analyses match your search.</p>
					</div>
				{:else}
					<GalleryGrid analyses={filteredAndSortedAnalyses} onDelete={requestDelete} />
				{/if}
			{/if}
		{/if}
	</main>
</div>

<ConfirmDialog
	show={deleteConfirmId !== null}
	title="Delete Analysis"
	message="Are you sure you want to delete this analysis? This action cannot be undone."
	confirmText="Delete"
	cancelText="Cancel"
	onConfirm={confirmDelete}
	onCancel={cancelDelete}
/>

<style>
	.container {
		max-width: 1200px;
		margin: 0 auto;
		padding: var(--space-7) var(--space-6);
		height: 100%;
		overflow: auto;
		box-sizing: border-box;
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-6);
		margin-bottom: var(--space-8);
		padding-bottom: var(--space-6);
		border-bottom: 1px solid var(--border-primary);
	}

	.header-text h1 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-2xl);
		font-weight: var(--font-semibold);
	}

	.subtitle {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
	}

	.loading {
		padding: var(--space-4) 0;
	}

	.skeleton-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--space-4);
	}

	.skeleton-card {
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
		background: var(--bg-primary);
	}

	.skeleton-thumbnail {
		width: 100%;
		aspect-ratio: 16 / 9;
		background: linear-gradient(
			90deg,
			var(--bg-tertiary) 25%,
			var(--bg-hover) 50%,
			var(--bg-tertiary) 75%
		);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
	}

	.skeleton-content {
		padding: var(--space-4);
	}

	.skeleton-title,
	.skeleton-text {
		height: 14px;
		background: linear-gradient(
			90deg,
			var(--bg-tertiary) 25%,
			var(--bg-hover) 50%,
			var(--bg-tertiary) 75%
		);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-3);
	}

	.skeleton-title {
		height: 16px;
		width: 70%;
	}

	.skeleton-text.small {
		width: 50%;
	}

	@keyframes shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}

	.error-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-12) var(--space-6);
		text-align: center;
		min-height: 400px;
	}

	.error-icon {
		width: 48px;
		height: 48px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		font-size: var(--text-xl);
		font-weight: var(--font-bold);
		margin-bottom: var(--space-6);
	}

	.error-state h2 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-lg);
		font-weight: var(--font-semibold);
	}

	.error-state p {
		margin: 0 0 var(--space-6) 0;
		font-size: var(--text-sm);
		max-width: 400px;
	}

	.no-results {
		text-align: center;
		padding: var(--space-12) var(--space-6);
		border: 1px dashed var(--border-primary);
		border-radius: var(--radius-sm);
	}

	.no-results p {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
	}

	@media (max-width: 768px) {
		.container {
			padding: var(--space-4);
		}

		.page-header {
			flex-direction: column;
			align-items: stretch;
		}

		.btn-new {
			width: 100%;
			justify-content: center;
		}

		.skeleton-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
