<script lang="ts">
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { getAllColumnTypes } from '$lib/utils/columnTypes';
	import { onClickOutside } from 'runed';

	interface Props {
		value: string;
		onChange: (value: string) => void;
		placeholder?: string;
	}

	let { value = $bindable(), onChange, placeholder = 'Select type...' }: Props = $props();

	let menuOpen = $state(false);
	let menuRef = $state<HTMLElement>();
	let searchQuery = $state('');
	let searchInputRef = $state<HTMLInputElement>();

	const allColumnTypes = getAllColumnTypes();
	let filteredTypes = $derived(
		searchQuery
			? allColumnTypes.filter(
					(t) =>
						t.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
						t.type.toLowerCase().includes(searchQuery.toLowerCase())
				)
			: allColumnTypes
	);
	let selectedType = $derived(allColumnTypes.find((t) => t.type === value));

	function selectType(typeValue: string) {
		onChange(typeValue);
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
		{#if selectedType}
			<ColumnTypeBadge columnType={selectedType.type} size="sm" />
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
					placeholder="Search types..."
					class="column-search-input"
				/>
			</div>
			<div class="column-options">
				{#each filteredTypes as typeConfig (typeConfig.type)}
					<button
						type="button"
						class="column-option type-option"
						class:selected={value === typeConfig.type}
						onclick={() => selectType(typeConfig.type)}
						role="option"
						aria-selected={value === typeConfig.type}
						title={typeConfig.description}
					>
						<ColumnTypeBadge columnType={typeConfig.type} size="sm" />
					</button>
				{:else}
					<div class="no-results">No types found</div>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	/* All styles defined globally in app.css */
</style>
