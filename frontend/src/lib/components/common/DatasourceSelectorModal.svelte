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
		class="modal-backdrop"
		onclick={handleClose}
		onkeydown={handleBackdropKeydown}
		role="button"
		tabindex="0"
		aria-label="Close modal"
	>
		<div
			class="modal"
			bind:this={modalRef}
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-labelledby="modal-title"
			tabindex="-1"
		>
			<div class="modal-header">
				<h2 id="modal-title">{mode === 'change' ? 'Change Datasource' : 'Add Datasource'}</h2>
				<button class="modal-close" onclick={handleClose} aria-label="Close">
					<X size={20} />
				</button>
			</div>
			<div class="modal-body">
				<input
					class="search-input"
					type="text"
					bind:this={searchInput}
					bind:value={searchQuery}
					placeholder="Search datasources..."
				/>
				<div class="datasource-list">
					{#if isLoading}
						<div class="list-empty">Loading...</div>
					{:else if filteredDatasources.length === 0}
						<div class="list-empty">
							{searchQuery ? 'No matching datasources' : 'No datasources available'}
						</div>
					{:else}
						{#each filteredDatasources as ds (ds.id)}
							<button class="datasource-item" onclick={() => handleSelect(ds.id, ds.name)}>
								<span class="datasource-name">{ds.name}</span>
								<span class="datasource-type">
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

<style>
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background-color: var(--overlay-bg);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
		padding: var(--space-4);
		animation: fadeIn var(--transition);
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	.modal {
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		max-width: 480px;
		width: 100%;
		max-height: 80vh;
		display: flex;
		flex-direction: column;
		animation: slideIn var(--transition);
	}

	@keyframes slideIn {
		from {
			transform: translateY(-10px);
			opacity: 0;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}

	.modal:focus {
		outline: none;
	}

	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-4);
		border-bottom: 1px solid var(--panel-border);
	}

	.modal-header h2 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-primary);
	}

	.modal-close {
		background: transparent;
		border: none;
		padding: var(--space-1);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		transition: all var(--transition);
	}

	.modal-close:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.modal-body {
		padding: var(--space-4);
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.search-input {
		width: 100%;
		padding: var(--space-3) var(--space-3);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		color: var(--fg-primary);
		background-color: var(--bg-primary);
		transition: border-color var(--transition);
	}

	.search-input:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.datasource-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-height: 300px;
		overflow-y: auto;
	}

	.datasource-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-3);
		background: transparent;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		cursor: pointer;
		text-align: left;
		transition: all var(--transition);
	}

	.datasource-item:hover {
		background-color: var(--bg-hover);
		border-color: var(--panel-border);
	}

	.datasource-name {
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--fg-primary);
	}

	.datasource-type {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--fg-muted);
	}

	.list-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-8);
		color: var(--fg-muted);
		font-size: var(--text-sm);
	}

	@media (max-width: 640px) {
		.modal {
			max-width: 100%;
		}
	}
</style>
