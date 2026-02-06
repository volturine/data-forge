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
				<div
					class="flex gap-2 border-b p-2"
					style="border-color: var(--border-secondary); background-color: var(--bg-secondary);"
				>
					<button
						type="button"
						class="select-action-btn flex-1 cursor-pointer rounded-sm border bg-transparent px-2 py-1 text-xs transition-all"
						onclick={(e) => {
							e.stopPropagation();
							selectAll();
						}}
						style="border-color: var(--border-primary); color: var(--fg-secondary);"
					>
						Select All {searchQuery ? 'Filtered' : ''}
					</button>
					<button
						type="button"
						class="select-action-btn flex-1 cursor-pointer rounded-sm border bg-transparent px-2 py-1 text-xs transition-all"
						onclick={(e) => {
							e.stopPropagation();
							deselectAll();
						}}
						style="border-color: var(--border-primary); color: var(--fg-secondary);"
					>
						Clear
					</button>
				</div>
			{/if}
			<div class="column-options">
				{#each filteredColumns as column (column.name)}
					<label
						class="multi-select-option flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2 transition-colors"
						style="color: var(--fg-primary);"
					>
						<input
							type="checkbox"
							checked={selectedSet.has(column.name)}
							onchange={() => toggleColumn(column.name)}
							onclick={(e) => e.stopPropagation()}
							class="m-0 cursor-pointer"
							style="accent-color: var(--accent-primary);"
						/>
						<span class="flex flex-1 items-center justify-start gap-2">
							<ColumnTypeBadge columnType={column.dtype} size="xs" />
							<span class="text-left text-sm" style="color: var(--fg-primary);">{column.name}</span>
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
	<div
		class="mt-2 max-h-[60px] overflow-y-auto rounded-sm border p-2 text-xs"
		style="background-color: var(--bg-secondary); border-color: var(--border-secondary); color: var(--fg-secondary);"
	>
		{value.join(', ')}
	</div>
{/if}

<style>
	.select-action-btn:hover {
		background-color: var(--bg-hover);
		border-color: var(--accent-primary);
		color: var(--accent-primary);
	}

	.multi-select-option:hover {
		background-color: var(--bg-hover);
	}
</style>
