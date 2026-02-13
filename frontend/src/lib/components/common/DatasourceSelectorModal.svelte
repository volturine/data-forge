<script lang="ts">
	import { onClickOutside, Debounced } from 'runed';
	import { X } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';

	interface Props {
		show: boolean;
		datasources: DataSource[];
		isLoading?: boolean;
		mode?: 'add' | 'change';
		onSelect: (id: string, name: string) => void;
		onClose: () => void;
	}

	let { show, datasources, isLoading = false, mode = 'add', onSelect, onClose }: Props = $props();

	let searchQuery = $state('');
	let debouncedSearch = new Debounced(() => searchQuery, 200);
	let modalRef = $state<HTMLElement>();
	let searchInput = $state<HTMLInputElement>();

	onClickOutside(
		() => modalRef,
		() => handleClose(),
		{ immediate: true }
	);

	let filteredDatasources = $derived(
		datasources.filter((ds) => {
			const query = debouncedSearch.current.toLowerCase().trim();
			if (!query) return true;
			return ds.name.toLowerCase().includes(query);
		})
	);

	function handleClose() {
		onClose();
		searchQuery = '';
	}

	function handleSelect(datasourceId: string, name: string) {
		onSelect(datasourceId, name);
		handleClose();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			handleClose();
		}
	}

	function handleBackdropKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			handleClose();
		}
	}

	$effect(() => {
		if (show) {
			document.body.style.overflow = 'hidden';
		} else {
			document.body.style.overflow = '';
		}

		return () => {
			document.body.style.overflow = '';
		};
	});

	$effect(() => {
		if (show && searchInput) {
			searchInput.focus();
		}
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if show}
	<div
		class="fixed inset-0 z-1000 flex items-center justify-center p-4 bg-overlay animate-fade-in"
		onclick={handleClose}
		onkeydown={handleBackdropKeydown}
		role="button"
		tabindex="0"
		aria-label="Close modal"
	>
		<div
			class="flex max-h-[80vh] w-full max-w-120 flex-col border focus:outline-none max-sm:max-w-full bg-panel border-tertiary animate-slide-up"
			bind:this={modalRef}
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-labelledby="modal-title"
			tabindex="-1"
		>
			<div class="flex items-center justify-between border-b p-4 border-tertiary">
				<h2 id="modal-title" class="m-0 text-sm font-semibold text-fg-primary">
					{mode === 'change' ? 'Change Datasource' : 'Add Datasource'}
				</h2>
				<button
					class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
					onclick={handleClose}
					aria-label="Close"
				>
					<X size={20} />
				</button>
			</div>
			<div class="flex flex-col gap-4 overflow-y-auto p-4">
				<input
				class="w-full border px-3 py-3 text-sm focus:outline-none border-tertiary text-fg-primary bg-primary focus:border-accent-primary"
					type="text"
					bind:this={searchInput}
					bind:value={searchQuery}
					placeholder="Search datasources..."
				/>
				<div class="flex max-h-75 flex-col gap-1 overflow-y-auto">
					{#if isLoading}
						<div class="flex items-center justify-center p-8 text-sm text-fg-muted">Loading...</div>
					{:else if filteredDatasources.length === 0}
						<div class="flex items-center justify-center p-8 text-sm text-fg-muted">
							{searchQuery ? 'No matching datasources' : 'No datasources available'}
						</div>
					{:else}
						{#each filteredDatasources as ds (ds.id)}
							<button
								class="flex cursor-pointer items-center justify-between border border-transparent bg-transparent p-3 text-left hover:bg-hover hover:border-tertiary"
								onclick={() => handleSelect(ds.id, ds.name)}
							>
								<span class="text-sm font-medium text-fg-primary">{ds.name}</span>
								<span class="flex items-center gap-1 text-fg-muted">
									{#if ds.source_type === 'file'}
										<FileTypeBadge path={ds.config.file_path as string} size="sm" showIcon={true} />
									{:else}
										<FileTypeBadge
											sourceType={ds.source_type as 'database' | 'api' | 'iceberg' | 'duckdb'}
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
		</div>
	</div>
{/if}
