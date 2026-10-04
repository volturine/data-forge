<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { goto } from '$app/navigation';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import { resolve } from '$app/paths';
	import {
		deleteAnalysis,
		duplicateAnalysis,
		favoriteAnalysis,
		listAnalyses,
		unfavoriteAnalysis
	} from '$lib/api/analysis';
	import GalleryGrid from '$lib/components/gallery/GalleryGrid.svelte';
	import EmptyState from '$lib/components/gallery/EmptyState.svelte';
	import AnalysisFilters from '$lib/components/gallery/AnalysisFilters.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import { Plus } from '@lucide/svelte';
	import type { SortOption } from '$lib/components/gallery/AnalysisFilters.svelte';
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { toEpochDisplay } from '$lib/utils/datetime';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { button, css, input, spinner } from '$lib/styles/panda';
	import { favoriteStore } from '$lib/stores/favorites.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';

	const queryClient = useQueryClient();
	const ns = useNamespace();
	let deletedAnalysisIds = $state<string[]>([]);

	const query = createQuery(() => ({
		queryKey: ['analyses', ns.value],
		queryFn: async ({ signal }) => {
			const result = await listAnalyses({ signal });
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value.filter((analysis) => !deletedAnalysisIds.includes(analysis.id));
		},
		// Analyses can be created or removed from another page, tab, or user.
		// Refresh on every gallery mount so navigation never presents a cached
		// list that omits a just-created analysis.
		staleTime: 0,
		refetchOnMount: 'always',
		enabled: !ns.switching
	}));

	let searchQuery = $state('');
	let sortOption = $state<SortOption>('newest');

	if (typeof window !== 'undefined') {
		void idbGet<string>('analysis-search').then((value) => {
			if (value !== null) searchQuery = value;
		});
		void idbGet<SortOption>('analysis-sort').then((value) => {
			if (value !== null) sortOption = value;
		});
	}

	// Selection state
	let deleteError = $state('');
	const selectedIds = new SvelteSet<string>();
	let deleteConfirmId = $state<string | null>(null);
	let bulkDeleteConfirm = $state(false);
	let duplicateSource = $state<AnalysisGalleryItem | null>(null);
	let duplicateName = $state('');
	let duplicateDescription = $state('');
	let duplicateError = $state('');
	let duplicating = $state(false);
	const favoriteMutationVersions = new SvelteMap<string, number>();

	const filteredAndSortedAnalyses = $derived.by(() => {
		if (!query.data) return [];

		let result = query.data.filter((analysis) => !deletedAnalysisIds.includes(analysis.id));

		if (searchQuery) {
			const lowerQuery = searchQuery.toLowerCase();
			result = result.filter((analysis) => analysis.name.toLowerCase().includes(lowerQuery));
		}

		result.sort((a, b) => {
			const left = toEpochDisplay(a.updated_at);
			const right = toEpochDisplay(b.updated_at);
			switch (sortOption) {
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

	function handleSearch(query: string) {
		searchQuery = query;
		void idbSet('analysis-search', query);
	}

	function handleSort(option: SortOption) {
		sortOption = option;
		void idbSet('analysis-sort', option);
	}

	function toggleSelect(id: string) {
		if (selectedIds.has(id)) {
			selectedIds.delete(id);
			return;
		}
		selectedIds.add(id);
	}

	function selectAll() {
		selectedIds.clear();
		for (const a of filteredAndSortedAnalyses) {
			selectedIds.add(a.id);
		}
	}

	function clearSelection() {
		selectedIds.clear();
	}

	function requestDelete(id: string) {
		deleteConfirmId = id;
	}

	function removeAnalysesFromCaches(ids: Iterable<string>) {
		const idSet = new Set(ids);
		queryClient.setQueryData<AnalysisGalleryItem[]>(['analyses', ns.value], (current) =>
			current?.filter((analysis) => !idSet.has(analysis.id))
		);
		queryClient.setQueryData<AnalysisGalleryItem[]>(['favorite-analyses', ns.value], (current) =>
			current?.filter((analysis) => !idSet.has(analysis.id))
		);
	}

	function markAnalysesDeleted(ids: Iterable<string>) {
		const next = new SvelteSet(deletedAnalysisIds);
		for (const id of ids) next.add(id);
		deletedAnalysisIds = [...next];
	}

	function restoreAnalyses(ids: Iterable<string>) {
		const restored = new Set(ids);
		deletedAnalysisIds = deletedAnalysisIds.filter((id) => !restored.has(id));
		void queryClient.invalidateQueries({ queryKey: ['analyses', ns.value], exact: true });
	}

	async function toggleFavorite(id: string) {
		const analysesKey = ['analyses', ns.value] as const;
		const favoritesKey = ['favorite-analyses', ns.value] as const;
		const version = (favoriteMutationVersions.get(id) ?? 0) + 1;
		favoriteMutationVersions.set(id, version);
		const next = !favoriteStore.isFavorite(id);
		const previousFavorite = !next;
		const previousAnalyses = queryClient.getQueryData<AnalysisGalleryItem[]>(analysesKey);
		const previousFavorites = queryClient.getQueryData<AnalysisGalleryItem[]>(favoritesKey);
		const analysis =
			previousAnalyses?.find((item) => item.id === id) ??
			query.data?.find((item) => item.id === id);

		// Publish the interaction immediately. The API is still authoritative,
		// but the gallery and sidebar must not wait for a slow control-plane
		// round-trip before reflecting a click.
		favoriteStore.apply(id, next);
		queryClient.setQueryData<AnalysisGalleryItem[]>(analysesKey, (current) =>
			current?.map((item) => (item.id === id ? { ...item, is_favorite: next } : item))
		);
		queryClient.setQueryData<AnalysisGalleryItem[]>(favoritesKey, (current) => {
			if (!current && !analysis) return current;
			const existing = current ?? [];
			const withoutCurrent = existing.filter((item) => item.id !== id);
			if (!next) return withoutCurrent;
			return analysis ? [...withoutCurrent, { ...analysis, is_favorite: true }] : existing;
		});

		// Stop an older in-flight response from restoring the pre-mutation
		// favorite list after the optimistic state has been published.
		const mutation = next ? favoriteAnalysis(id) : unfavoriteAnalysis(id);
		await queryClient.cancelQueries({ queryKey: favoritesKey, exact: true }, { revert: false });
		const result = await mutation;
		if (result.isErr()) {
			if (favoriteMutationVersions.get(id) === version) {
				favoriteStore.apply(id, previousFavorite);
				queryClient.setQueryData(analysesKey, previousAnalyses);
				queryClient.setQueryData(favoritesKey, previousFavorites);
				deleteError = result.error.message;
			}
			return;
		}
		if (favoriteMutationVersions.get(id) !== version) return;
		const isFavorite = result.value.is_favorite;
		favoriteStore.apply(id, isFavorite);
		// The mutation response is authoritative. Update both visible caches
		// synchronously so a refetch cannot briefly remove the sidebar link.
		queryClient.setQueryData<AnalysisGalleryItem[]>(analysesKey, (current) =>
			current?.map((analysis) =>
				analysis.id === id ? { ...analysis, is_favorite: isFavorite } : analysis
			)
		);
		const currentAnalysis = queryClient
			.getQueryData<AnalysisGalleryItem[]>(analysesKey)
			?.find((item) => item.id === id);
		queryClient.setQueryData<AnalysisGalleryItem[]>(favoritesKey, (current) => {
			if (!current && !currentAnalysis) return current;
			const existing = current ?? [];
			const withoutCurrent = existing.filter((item) => item.id !== id);
			if (!isFavorite) return withoutCurrent;
			return currentAnalysis
				? [...withoutCurrent, { ...currentAnalysis, is_favorite: true }]
				: existing;
		});
	}

	function requestDuplicate(analysis: AnalysisGalleryItem) {
		duplicateSource = analysis;
		duplicateName = `Copy of ${analysis.name}`;
		duplicateDescription = '';
		duplicateError = '';
		duplicating = false;
	}

	async function confirmDelete() {
		if (!deleteConfirmId) return;
		deleteError = '';
		const id = deleteConfirmId;
		const analysis = query.data?.find((item) => item.id === id);
		if (!analysis) {
			deleteError = 'The analysis is no longer available.';
			deleteConfirmId = null;
			return;
		}

		// Stop an older gallery fetch from writing a pre-delete list after the
		// mutation commits. The optimistic edit below is the visible state
		// transition; a failed mutation restores the row from a refetch.
		markAnalysesDeleted([id]);
		removeAnalysesFromCaches([id]);
		selectedIds.delete(id);
		deleteConfirmId = null;
		// Publish the visible deletion before waiting on an older gallery fetch.
		// The list must not stay on the old card while the network mutation is
		// being scheduled. `revert: false` prevents that fetch from restoring the
		// pre-delete snapshot after the optimistic update.
		await queryClient.cancelQueries(
			{ queryKey: ['analyses', ns.value], exact: true },
			{ revert: false }
		);

		const result = await deleteAnalysis(id, analysis.revision);
		if (result.isErr()) {
			restoreAnalyses([id]);
			deleteError = `Failed to delete: ${result.error.message}`;
		}
	}

	function cancelDelete() {
		deleteConfirmId = null;
	}

	function requestBulkDelete() {
		bulkDeleteConfirm = true;
	}

	async function confirmBulkDelete() {
		deleteError = '';
		const idsToDelete = Array.from(selectedIds);
		const analysesById = new Map((query.data ?? []).map((analysis) => [analysis.id, analysis]));
		markAnalysesDeleted(idsToDelete);
		removeAnalysesFromCaches(idsToDelete);
		selectedIds.clear();
		bulkDeleteConfirm = false;
		// Do not make the gallery wait for an in-flight list request before
		// reflecting the deletion. The deleted-id guard also keeps an older
		// response from reintroducing these cards while the DELETEs complete.
		await queryClient.cancelQueries(
			{ queryKey: ['analyses', ns.value], exact: true },
			{ revert: false }
		);

		const outcomes = await Promise.all(
			idsToDelete.map(async (id) => {
				const analysis = analysesById.get(id);
				if (!analysis) return { id, error: 'The analysis is no longer available.' };
				const result = await deleteAnalysis(id, analysis.revision);
				return result.isErr() ? { id, error: result.error.message } : { id, error: null };
			})
		);
		const failed = outcomes.filter((outcome) => outcome.error !== null);

		if (failed.length > 0) {
			restoreAnalyses(failed.map((outcome) => outcome.id));
			deleteError = `Failed to delete ${failed.length} analysis${failed.length > 1 ? 'es' : ''}.`;
		}
	}

	function cancelBulkDelete() {
		bulkDeleteConfirm = false;
	}

	async function confirmDuplicate() {
		if (!duplicateSource || !duplicateName.trim()) return;
		duplicating = true;
		duplicateError = '';
		const result = await duplicateAnalysis(duplicateSource.id, {
			name: duplicateName.trim(),
			description: duplicateDescription.trim() || null
		});
		result.match(
			(analysis) => {
				duplicateSource = null;
				void goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: false });
			},
			(err) => {
				duplicateError = err.message;
				duplicating = false;
			}
		);
	}

	function closeDuplicate() {
		duplicateSource = null;
		duplicateName = '';
		duplicateDescription = '';
		duplicateError = '';
		duplicating = false;
	}

	const deleteConfirmName = $derived.by(() => {
		if (!deleteConfirmId || !query.data) return '';
		const analysis = query.data.find((a) => a.id === deleteConfirmId);
		return analysis?.name ?? '';
	});
</script>

<div
	class={css({
		marginX: 'auto',
		boxSizing: 'border-box',
		maxWidth: 'page',
		paddingX: '8',
		paddingY: '8',
		md: { paddingX: '4', paddingY: '4' }
	})}
>
	<header
		class={css({
			marginBottom: '8',
			display: 'flex',
			flexDirection: 'column',
			alignItems: 'stretch',
			justifyContent: 'space-between',
			gap: '6',
			borderBottomWidth: '1',
			paddingBottom: '6',
			md: { flexDirection: 'row', alignItems: 'flex-start' }
		})}
	>
		<div>
			<h1 class={css({ margin: '0', marginBottom: '2', fontSize: '2xl', fontWeight: 'semibold' })}>
				Analyses
			</h1>
			<p class={css({ margin: '0', fontSize: 'sm', color: 'fg.tertiary' })}>
				Browse and manage your data analyses
			</p>
		</div>
		<a
			href={resolve('/analysis/new')}
			class={css({
				width: '100%',
				justifyContent: 'center',
				backgroundColor: 'accent.primary',
				color: 'fg.inverse',
				borderWidth: '1',
				paddingX: '4',
				paddingY: '2',
				display: 'inline-flex',
				alignItems: 'center',
				gap: '2',
				textDecoration: 'none',
				fontWeight: 'medium',
				fontSize: 'sm',
				md: { width: 'auto' }
			})}
		>
			<Plus size={16} />
			New Analysis
		</a>
	</header>

	{#if deleteError}
		<div class={css({ marginBottom: '4' })}>
			<Callout tone="error">{deleteError}</Callout>
		</div>
	{/if}

	<main>
		{#if query.isPending}
			<div
				class={css({
					display: 'flex',
					height: '100%',
					alignItems: 'center',
					justifyContent: 'center'
				})}
			>
				<div class={spinner()}></div>
			</div>
		{:else if query.isError}
			<div
				class={css({
					display: 'flex',
					minHeight: 'listLg',
					flexDirection: 'column',
					alignItems: 'center',
					justifyContent: 'center',
					paddingX: '6',
					paddingY: '12',
					textAlign: 'center'
				})}
			>
				<div
					class={css({
						marginBottom: '6',
						display: 'flex',
						height: 'logo',
						width: 'logo',
						alignItems: 'center',
						justifyContent: 'center',
						fontSize: 'xl',
						fontWeight: 'bold'
					})}
				>
					!
				</div>
				<h2 class={css({ margin: '0', marginBottom: '2', fontSize: 'lg', fontWeight: 'semibold' })}>
					Failed to load analyses
				</h2>
				<p class={css({ margin: '0', marginBottom: '6', maxWidth: 'panel', fontSize: 'sm' })}>
					{query.error.message}
				</p>
				<button class={button({ variant: 'primary' })} onclick={() => query.refetch()}>
					Try again
				</button>
			</div>
		{:else if query.data}
			{#if query.data.length === 0}
				<EmptyState onCreate={() => void goto(resolve('/analysis/new'))} />
			{:else}
				<AnalysisFilters
					{searchQuery}
					{sortOption}
					onSearch={handleSearch}
					onSort={handleSort}
					{selectionCount}
					onSelectAll={selectAll}
					onClearSelection={clearSelection}
					onBulkDelete={requestBulkDelete}
				/>
				{#if filteredAndSortedAnalyses.length === 0}
					<div
						class={css({
							borderWidth: '1',
							borderStyle: 'dashed',
							paddingX: '6',
							paddingY: '12',
							textAlign: 'center'
						})}
					>
						<p class={css({ color: 'fg.tertiary', margin: '0', fontSize: 'sm' })}>
							No analyses match your search.
						</p>
					</div>
				{:else}
					<GalleryGrid
						analyses={filteredAndSortedAnalyses}
						{selectedIds}
						favoriteIds={favoriteStore.ids}
						onDelete={requestDelete}
						onDuplicate={requestDuplicate}
						onToggleFavorite={toggleFavorite}
						onToggleSelect={toggleSelect}
					/>
				{/if}
			{/if}
		{/if}
	</main>
</div>

<ConfirmDialog
	show={deleteConfirmId !== null}
	heading="Delete Analysis"
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
	heading="Delete Analyses"
	message={`Are you sure you want to delete ${selectionCount} analysis${selectionCount > 1 ? 'es' : ''}? This action cannot be undone.`}
	confirmText="Delete"
	cancelText="Cancel"
	onConfirm={confirmBulkDelete}
	onCancel={cancelBulkDelete}
/>

<BaseModal
	open={duplicateSource !== null}
	onClose={closeDuplicate}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'full',
		maxWidth: 'panel',
		overflow: 'hidden',
		borderWidth: '1',
		backgroundColor: 'bg.primary'
	})}
	ariaLabelledby="duplicate-analysis-title"
	ariaDescribedby="duplicate-analysis-description"
	{content}
/>

{#snippet content()}
	<PanelHeader>
		{#snippet title()}
			<h2
				id="duplicate-analysis-title"
				class={css({ margin: '0', fontSize: 'md', fontWeight: 'semibold' })}
			>
				Duplicate Analysis
			</h2>
		{/snippet}
	</PanelHeader>

	<div class={css({ display: 'grid', gap: '4', padding: '6' })}>
		<p
			id="duplicate-analysis-description"
			class={css({ margin: '0', fontSize: 'sm', color: 'fg.tertiary' })}
		>
			Create an independent copy of {duplicateSource?.name ?? 'this analysis'}. Output identities
			will be regenerated.
		</p>
		{#if duplicateError}
			<Callout tone="error">{duplicateError}</Callout>
		{/if}
		<label class={css({ display: 'grid', gap: '1' })}>
			<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Name</span>
			<input class={input({ variant: 'dialog' })} bind:value={duplicateName} />
		</label>
		<label class={css({ display: 'grid', gap: '1' })}>
			<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Description</span>
			<textarea
				rows="4"
				class={input({ variant: 'dialog' })}
				bind:value={duplicateDescription}
				placeholder="Optional override. Leave empty to reuse the source description."></textarea>
		</label>
	</div>

	<PanelFooter>
		<button type="button" class={button({ variant: 'secondary' })} onclick={closeDuplicate}>
			Cancel
		</button>
		<button
			type="button"
			class={button({ variant: 'primary' })}
			disabled={duplicating || !duplicateName.trim()}
			onclick={confirmDuplicate}
		>
			{duplicating ? 'Duplicating...' : 'Duplicate'}
		</button>
	</PanelFooter>
{/snippet}
