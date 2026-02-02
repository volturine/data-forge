<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { SvelteSet } from 'svelte/reactivity';

	const uid = $props.id();

	interface SelectConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: SelectConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	const safeColumns = $derived(Array.isArray(config.columns) ? config.columns : []);

	// Use SvelteSet for O(1) lookups
	const selectedSet = $derived(new SvelteSet(safeColumns));

	function toggleColumn(columnName: string) {
		if (selectedSet.has(columnName)) {
			config.columns = safeColumns.filter((c) => c !== columnName);
			return;
		}
		config.columns = [...safeColumns, columnName];
	}

	function selectAll() {
		config.columns = schema.columns.map((c) => c.name);
	}

	function deselectAll() {
		config.columns = [];
	}
</script>

<div class="config-panel" role="region" aria-label="Select columns configuration">
	<h3>Select Columns</h3>

	<div class="bulk-actions">
		<button
			id="{uid}-select-all"
			data-testid="select-select-all-button"
			type="button"
			onclick={selectAll}
			aria-label="Select all columns"
		>
			Select All
		</button>
		<button
			id="{uid}-deselect-all"
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
					id="{uid}-col-{column.name}"
					data-testid={`select-checkbox-${column.name}`}
					type="checkbox"
					checked={selectedSet.has(column.name)}
					onchange={() => toggleColumn(column.name)}
					aria-label={`Select column ${column.name}`}
				/>
				<span class="column-name">{column.name}</span>
				<span class="column-type">({column.dtype})</span>
			</label>
		{/each}
	</div>

	{#if safeColumns.length > 0}
		<div id="{uid}-summary" class="selected-summary" aria-live="polite">
			<strong>Selected ({safeColumns.length}):</strong>
			<div class="selected-names">
				{safeColumns.join(', ')}
			</div>
		</div>
	{/if}
</div>
