<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { onClickOutside } from 'runed';

	interface Props {
		schema: Schema;
		value: string[];
		onChange: (value: string[]) => void;
		placeholder?: string;
		filter?: (column: { name: string; dtype: string }) => boolean;
		showSelectAll?: boolean;
	}

	let {
		schema,
		value = $bindable([]),
		onChange,
		placeholder = 'Select columns...',
		filter,
		showSelectAll = true
	}: Props = $props();

	let menuOpen = $state(false);
	let menuRef = $state<HTMLElement>();
	let searchQuery = $state('');
	let searchInputRef = $state<HTMLInputElement>();

	let columns = $derived(filter ? schema.columns.filter(filter) : schema.columns);
	let filteredColumns = $derived(
		searchQuery
			? columns.filter((col) => col.name.toLowerCase().includes(searchQuery.toLowerCase()))
			: columns
	);
	let selectedSet = $derived(new Set(value));
	let selectedCount = $derived(value.length);

	function toggleColumn(columnName: string) {
		if (selectedSet.has(columnName)) {
			onChange(value.filter((c) => c !== columnName));
		} else {
			onChange([...value, columnName]);
		}
	}

	function selectAll() {
		onChange(filteredColumns.map((c) => c.name));
	}

	function deselectAll() {
		onChange([]);
	}

	function openMenu() {
		menuOpen = true;
		setTimeout(() => searchInputRef?.focus(), 0);
	}

	onClickOutside(
		() => menuRef,
		() => {
			if (menuOpen) {
				menuOpen = false;
				searchQuery = '';
			}
		}
	);
</script>

<div class="column-select multi-select" bind:this={menuRef}>
	<button type="button" class="column-trigger" onclick={openMenu} aria-expanded={menuOpen}>
		{#if selectedCount > 0}
			<span class="column-label">{selectedCount} column{selectedCount !== 1 ? 's' : ''}</span>
		{:else}
			<span class="column-placeholder">{placeholder}</span>
		{/if}
		<span class="chevron">▾</span>
	</button>
	{#if menuOpen}
		<div class="column-menu" role="listbox" aria-multiselectable="true">
			<div class="column-search">
				<input
					bind:this={searchInputRef}
					bind:value={searchQuery}
					type="text"
					placeholder="Search columns..."
					class="column-search-input"
				/>
			</div>
			{#if showSelectAll}
				<div class="multi-select-actions">
					<button
						type="button"
						class="select-action-btn"
						onclick={(e) => {
							e.stopPropagation();
							selectAll();
						}}
					>
						Select All {searchQuery ? 'Filtered' : ''}
					</button>
					<button
						type="button"
						class="select-action-btn"
						onclick={(e) => {
							e.stopPropagation();
							deselectAll();
						}}
					>
						Clear
					</button>
				</div>
			{/if}
			<div class="column-options">
				{#each filteredColumns as column (column.name)}
					<label class="column-option multi-select-option">
						<input
							type="checkbox"
							checked={selectedSet.has(column.name)}
							onchange={() => toggleColumn(column.name)}
							onclick={(e) => e.stopPropagation()}
						/>
						<span class="option-content">
							<ColumnTypeBadge columnType={column.dtype} size="xs" />
							<span class="column-name">{column.name}</span>
						</span>
					</label>
				{:else}
					<div class="no-results">No columns found</div>
				{/each}
			</div>
		</div>
	{/if}
</div>

{#if selectedCount > 0}
	<div class="selected-summary-compact">
		{value.join(', ')}
	</div>
{/if}

<style>
	/* Multi-select specific styles - base styles in app.css */
	.multi-select-actions {
		display: flex;
		gap: var(--space-2);
		padding: var(--space-2);
		border-bottom: 1px solid var(--border-secondary);
		background-color: var(--bg-secondary);
	}

	.select-action-btn {
		flex: 1;
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-xs);
		background-color: transparent;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		color: var(--fg-secondary);
		transition: all var(--transition);
	}

	.select-action-btn:hover {
		background-color: var(--bg-hover);
		border-color: var(--accent-primary);
		color: var(--accent-primary);
	}

	.multi-select-option {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		cursor: pointer;
		border-radius: var(--radius-sm);
		transition: background-color var(--transition);
		color: var(--fg-primary);
	}

	.multi-select-option:hover {
		background-color: var(--bg-hover);
	}

	.multi-select-option input[type='checkbox'] {
		margin: 0;
		cursor: pointer;
		accent-color: var(--accent-primary);
	}

	.option-content {
		display: flex;
		align-items: center;
		justify-content: flex-start;
		flex: 1;
		gap: var(--space-2);
	}

	.column-name {
		color: var(--fg-primary);
		font-size: var(--text-sm);
		text-align: left;
	}

	.selected-summary-compact {
		margin-top: var(--space-2);
		padding: var(--space-2);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		color: var(--fg-secondary);
		max-height: 60px;
		overflow-y: auto;
	}
</style>
