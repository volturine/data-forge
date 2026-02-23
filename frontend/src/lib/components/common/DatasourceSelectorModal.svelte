<script lang="ts">
	import { Debounced } from 'runed';
	import { X } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { SourceType } from '$lib/utils/fileTypes';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';

	interface Props {
		show: boolean;
		datasources: DataSource[];
		isLoading?: boolean;
		mode?: 'add' | 'change';
		sourceType?: 'datasource' | 'analysis';
		allowAnalysis?: boolean;
		analysisTabs?: Array<{ id: string; name: string }>;
		excludeTabId?: string | null;
		onSelect: (id: string, name: string, sourceType: 'datasource' | 'analysis') => void;
		onClose: () => void;
	}

	let {
		show,
		datasources,
		isLoading = false,
		mode = 'add',
		sourceType = 'datasource',
		allowAnalysis = true,
		analysisTabs = [],
		excludeTabId = null,
		onSelect,
		onClose
	}: Props = $props();

	let searchQuery = $state('');
	const debouncedSearch = new Debounced(() => searchQuery, 200);
	let searchInput = $state<HTMLInputElement>();
	let activeOverride = $state<'datasource' | 'analysis' | null>(null);
	const activeSource = $derived(activeOverride ?? (allowAnalysis ? sourceType : 'datasource'));

	const filteredDatasources = $derived(
		datasources.filter((ds) => {
			const query = debouncedSearch.current.toLowerCase().trim();
			if (!query) return true;
			return ds.name.toLowerCase().includes(query);
		})
	);
	const filteredTabs = $derived(
		analysisTabs.filter((tab) => {
			if (mode === 'change' && excludeTabId && tab.id === excludeTabId) return false;
			const query = debouncedSearch.current.toLowerCase().trim();
			if (!query) return true;
			return tab.name.toLowerCase().includes(query);
		})
	);

	function handleClose() {
		activeOverride = null;
		onClose();
		searchQuery = '';
	}

	function handleSelect(datasourceId: string, name: string) {
		onSelect(datasourceId, name, activeSource);
		handleClose();
	}

	function handleAnalysisTabSelect(entry: { id: string; name: string }) {
		onSelect(entry.id, entry.name, 'analysis');
		handleClose();
	}


	function handleBackdropKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			handleClose();
		}
	}

	// DOM: $derived can't focus the search input.
	$effect(() => {
		if (show && searchInput) {
			searchInput.focus();
		}
	});
</script>

<BaseModal
	open={show}
	onClose={handleClose}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass="flex max-h-[80vh] w-full max-w-120 flex-col border focus:outline-none max-sm:max-w-full bg-panel border-tertiary animate-slide-up"
	ariaLabelledby="modal-title"
	onBackdropKeydown={handleBackdropKeydown}
	content={content}
/>

{#snippet content()}
	<div class="flex items-center justify-between border-b p-4 border-tertiary">
		<h2 id="modal-title" class="m-0 text-sm font-semibold text-fg-primary">
			{mode === 'change' ? 'Change Datasource' : 'Add Datasource'}
		</h2>
		<button
			class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
			onclick={handleClose}
			aria-label="Close"
			type="button"
		>
			<X size={20} />
		</button>
	</div>
	<div class="flex flex-col gap-4 overflow-y-auto p-4">
		{#if allowAnalysis}
			<div class="flex items-center gap-1 border border-tertiary bg-tertiary p-1">
				<button
					class="flex-1 border-none bg-transparent px-3 py-2 text-xs font-semibold uppercase tracking-[0.08em]"
					class:text-fg-primary={activeSource === 'datasource'}
					class:text-fg-muted={activeSource !== 'datasource'}
					class:bg-panel={activeSource === 'datasource'}
					onclick={() => (activeOverride = 'datasource')}
					type="button"
				>
					Datasources
				</button>
				<button
					class="flex-1 border-none bg-transparent px-3 py-2 text-xs font-semibold uppercase tracking-[0.08em]"
					class:text-fg-primary={activeSource === 'analysis'}
					class:text-fg-muted={activeSource !== 'analysis'}
					class:bg-panel={activeSource === 'analysis'}
					onclick={() => (activeOverride = 'analysis')}
					type="button"
				>
					Analyses
				</button>
			</div>
		{/if}
		<input
			class="w-full border px-3 py-3 text-sm focus:outline-none border-tertiary text-fg-primary bg-primary focus:border-accent-primary"
			type="text"
			bind:this={searchInput}
			bind:value={searchQuery}
			placeholder={activeSource === 'analysis' ? 'Search analyses...' : 'Search datasources...'}
		/>
		<div class="flex max-h-75 flex-col gap-1 overflow-y-auto">
			{#if isLoading}
				<div class="flex items-center justify-center p-8 text-sm text-fg-muted">Loading...</div>
			{:else if activeSource === 'analysis' && allowAnalysis && filteredTabs.length === 0}
				<div class="flex items-center justify-center p-8 text-sm text-fg-muted">
					{searchQuery ? 'No matching analysis tabs' : 'No analysis tabs available'}
				</div>
			{:else if activeSource === 'datasource' && filteredDatasources.length === 0}
				<div class="flex items-center justify-center p-8 text-sm text-fg-muted">
					{searchQuery ? 'No matching datasources' : 'No datasources available'}
				</div>
			{:else if activeSource === 'analysis' && allowAnalysis}
				{#each filteredTabs as entry (entry.id)}
					<button
						class="flex cursor-pointer items-center justify-between border border-transparent bg-transparent p-3 text-left hover:bg-hover hover:border-tertiary"
						onclick={() => handleAnalysisTabSelect(entry)}
						type="button"
					>
						<span class="text-sm font-medium text-fg-primary">
							{entry.name}
						</span>
						<span class="text-xs text-fg-muted">analysis tab</span>
					</button>
				{/each}
			{:else}
				{#each filteredDatasources as ds (ds.id)}
					<button
						class="flex cursor-pointer items-center justify-between border border-transparent bg-transparent p-3 text-left hover:bg-hover hover:border-tertiary"
						onclick={() => handleSelect(ds.id, ds.name)}
						type="button"
					>
						<span class="text-sm font-medium text-fg-primary">{ds.name}</span>
						<span class="flex items-center gap-1 text-fg-muted">
							{#if ds.source_type === 'file'}
								<FileTypeBadge path={ds.config.file_path as string} size="sm" showIcon={true} />
							{:else}
								<FileTypeBadge
									sourceType={ds.source_type as SourceType}
									size="sm"
									showIcon={true}
								/>
							{/if}
						</span>
					</button>
				{/each}
			{/if}
		</div>
	</div>
{/snippet}
