<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { goto } from '$app/navigation';
	import { idbGet, idbSet } from '$lib/utils/indexeddb';
	import { SvelteSet } from 'svelte/reactivity';
	import { resolve } from '$app/paths';
	import { deleteAnalysis, duplicateAnalysis, listAnalyses } from '$lib/api/analysis';
	import GalleryGrid from '$lib/components/gallery/GalleryGrid.svelte';
	import EmptyState from '$lib/components/gallery/EmptyState.svelte';
	import AnalysisFilters from '$lib/components/gallery/AnalysisFilters.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import { Plus } from 'lucide-svelte';
	import type { SortOption } from '$lib/components/gallery/AnalysisFilters.svelte';
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { toEpochDisplay } from '$lib/utils/datetime';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, spinner } from '$lib/styles/panda';
	import { useNamespace } from '$lib/stores/namespace.svelte';

	const queryClient = useQueryClient();
	const ns = useNamespace();

	const query = createQuery(() => ({
		queryKey: ['analyses', ns.value],
		queryFn: async () => {
			const result = await listAnalyses();
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		},
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

	const filteredAndSortedAnalyses = $derived.by(() => {
		if (!query.data) return [];

		let result = [...query.data];

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

		const result = await deleteAnalysis(id);
		if (result.isOk()) {
			queryClient.invalidateQueries({ queryKey: ['analyses', ns.value] });
			selectedIds.delete(id);
			deleteConfirmId = null;
		} else {
			deleteError = `Failed to delete: ${result.error.message}`;
			deleteConfirmId = null;
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
		let failed = 0;

		for (const id of idsToDelete) {
			const result = await deleteAnalysis(id);
			if (result.isErr()) failed++;
		}

		queryClient.invalidateQueries({ queryKey: ['analyses', ns.value] });
		selectedIds.clear();
		bulkDeleteConfirm = false;

		if (failed > 0) {
			deleteError = `Failed to delete ${failed} analysis${failed > 1 ? 'es' : ''}.`;
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
				void goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
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
				<button
					class={css({
						backgroundColor: 'accent.primary',
						color: 'fg.inverse',
						borderWidth: '1',
						paddingX: '4',
						paddingY: '2'
					})}
					onclick={() => query.refetch()}
				>
					Try again
				</button>
			</div>
		{:else if query.data}
			{#if query.data.length === 0}
				<EmptyState />
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
						onDelete={requestDelete}
						onDuplicate={requestDuplicate}
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
			<input
				class={css({
					borderWidth: '1',
					backgroundColor: 'bg.primary',
					paddingX: '3',
					paddingY: '2'
				})}
				bind:value={duplicateName}
			/>
		</label>
		<label class={css({ display: 'grid', gap: '1' })}>
			<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Description</span>
			<textarea
				rows="4"
				class={css({
					borderWidth: '1',
					backgroundColor: 'bg.primary',
					paddingX: '3',
					paddingY: '2'
				})}
				bind:value={duplicateDescription}
				placeholder="Optional override. Leave empty to reuse the source description."
			></textarea>
		</label>
	</div>

	<PanelFooter>
		<button
			type="button"
			class={css({
				borderWidth: '1',
				backgroundColor: 'transparent',
				paddingX: '4',
				paddingY: '2'
			})}
			onclick={closeDuplicate}
		>
			Cancel
		</button>
		<button
			type="button"
			class={css({
				borderWidth: '1',
				backgroundColor: 'accent.primary',
				color: 'fg.inverse',
				paddingX: '4',
				paddingY: '2'
			})}
			disabled={duplicating || !duplicateName.trim()}
			onclick={confirmDuplicate}
		>
			{duplicating ? 'Duplicating...' : 'Duplicate'}
		</button>
	</PanelFooter>
{/snippet}
