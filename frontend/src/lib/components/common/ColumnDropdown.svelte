<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { onClickOutside } from 'runed';

	interface Props {
		schema: Schema;
		value: string;
		onChange: (value: string) => void;
		placeholder?: string;
		filter?: (column: { name: string; dtype: string }) => boolean;
	}

	let {
		schema,
		value = $bindable(),
		onChange,
		placeholder = 'Select column...',
		filter
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
	let selectedColumn = $derived(columns.find((col) => col.name === value));

	function selectColumn(columnName: string) {
		onChange(columnName);
		menuOpen = false;
		searchQuery = '';
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

<div class="column-select" bind:this={menuRef}>
	<button type="button" class="column-trigger" onclick={openMenu} aria-expanded={menuOpen}>
		{#if selectedColumn}
			<ColumnTypeBadge columnType={selectedColumn.dtype} size="xs" />
			<span class="column-label">{selectedColumn.name}</span>
		{:else}
			<span class="column-placeholder">{placeholder}</span>
		{/if}
		<span class="chevron">▾</span>
	</button>
	{#if menuOpen}
		<div class="column-menu" role="listbox">
			<div class="column-search">
				<input
					bind:this={searchInputRef}
					bind:value={searchQuery}
					type="text"
					placeholder="Search columns..."
					class="column-search-input"
				/>
			</div>
			<div class="column-options">
				{#each filteredColumns as column (column.name)}
					<button
						type="button"
						class="column-option"
						class:selected={value === column.name}
						onclick={() => selectColumn(column.name)}
						role="option"
						aria-selected={value === column.name}
					>
						<ColumnTypeBadge columnType={column.dtype} size="xs" />
						<span>{column.name}</span>
					</button>
				{:else}
					<div class="no-results">No columns found</div>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	/* All styles defined globally in app.css */
</style>
