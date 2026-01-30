<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { SvelteSet } from 'svelte/reactivity';

	interface SelectConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: SelectConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	// SvelteSet for UI state - derived from config
	// eslint-disable-next-line svelte/no-unnecessary-state-wrap
	let selectedColumns = $state(new SvelteSet<string>(config.columns ?? []));

	// When config changes (different step selected), reset the SvelteSet
	// This is a legitimate use of $effect for syncing external state changes
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

<div class="config-panel" role="region" aria-label="Select columns configuration">
	<h3>Select Columns</h3>

	<div class="bulk-actions">
		<button
			id="select-btn-select-all"
			data-testid="select-select-all-button"
			type="button"
			onclick={selectAll}
			aria-label="Select all columns"
		>
			Select All
		</button>
		<button
			id="select-btn-deselect-all"
			data-testid="select-deselect-all-button"
			type="button"
			onclick={deselectAll}
			aria-label="Deselect all columns"
		>
			Deselect All
		</button>
	</div>

	<div class="column-list" role="group" aria-label="Available columns">
		{#each schema.columns as column (column.name)}
			<label class="column-item">
				<input
					id={`select-checkbox-${column.name}`}
					data-testid={`select-checkbox-${column.name}`}
					type="checkbox"
					checked={selectedColumns.has(column.name)}
					onchange={() => toggleColumn(column.name)}
					aria-label={`Select column ${column.name}`}
				/>
				<span class="column-name">{column.name}</span>
				<span class="column-type">({column.dtype})</span>
			</label>
		{/each}
	</div>

	{#if selectedColumnNames.length > 0}
		<div id="select-summary-selected" class="selected-summary" aria-live="polite">
			<strong>Selected ({selectedColumnNames.length}):</strong>
			<div class="selected-names">
				{selectedColumnNames.join(', ')}
			</div>
		</div>
	{/if}
</div>
