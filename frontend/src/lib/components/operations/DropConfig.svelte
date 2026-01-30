<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { SvelteSet } from 'svelte/reactivity';

	interface DropConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: DropConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	// SvelteSet for UI state - derived from config
	// eslint-disable-next-line svelte/no-unnecessary-state-wrap
	let selectedColumns = $state(new SvelteSet<string>(config.columns ?? []));

	// When config changes (different step selected), reset the SvelteSet
	let lastConfig = $state(config);
	$effect(() => {
		if (config !== lastConfig) {
			selectedColumns = new SvelteSet<string>(config.columns ?? []);
			lastConfig = config;
		}
	});

	function toggleColumn(columnName: string) {
		if (selectedColumns.has(columnName)) {
			selectedColumns.delete(columnName);
		} else {
			selectedColumns.add(columnName);
		}
		// Update config directly
		config.columns = Array.from(selectedColumns);
	}

	function selectAll() {
		selectedColumns = new SvelteSet(schema.columns.map((c) => c.name));
		config.columns = Array.from(selectedColumns);
	}

	function deselectAll() {
		selectedColumns = new SvelteSet();
		config.columns = [];
	}

	let selectedColumnNames = $derived(Array.from(selectedColumns));
</script>

<div class="config-panel" role="region" aria-label="Drop columns configuration">
	<h3>Drop Columns</h3>

	<p class="description">Select the columns you want to drop (remove) from the dataset.</p>

	<div class="bulk-actions">
		<button
			id="drop-btn-select-all"
			data-testid="drop-select-all-button"
			type="button"
			onclick={selectAll}
			aria-label="Select all columns to drop"
		>
			Select All
		</button>
		<button
			id="drop-btn-deselect-all"
			data-testid="drop-deselect-all-button"
			type="button"
			onclick={deselectAll}
			aria-label="Deselect all columns"
		>
			Deselect All
		</button>
	</div>

	<div id="drop-column-list" class="column-list" role="group" aria-label="Available columns">
		{#each schema.columns as column (column.name)}
			<label class="column-item">
				<input
					id={`drop-checkbox-${column.name}`}
					data-testid={`drop-column-checkbox-${column.name}`}
					type="checkbox"
					checked={selectedColumns.has(column.name)}
					onchange={() => toggleColumn(column.name)}
					aria-label={`Drop column ${column.name}`}
				/>
				<span class="column-name">{column.name}</span>
				<span class="column-type">({column.dtype})</span>
			</label>
		{/each}
	</div>

	{#if selectedColumnNames.length > 0}
		<div id="drop-selected-summary" class="selected-summary warning" aria-live="polite">
			<strong>Columns to Drop ({selectedColumnNames.length}):</strong>
			<div class="selected-names">
				{selectedColumnNames.join(', ')}
			</div>
		</div>
	{:else}
		<div id="drop-warning" class="warning-box" role="alert">
			<strong>Warning:</strong> No columns selected. This operation will have no effect.
		</div>
	{/if}
</div>

<style>
	h3 {
		margin-bottom: var(--space-2);
	}
</style>
