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

	// Keep SvelteSet for UI
	let selectedColumns = $state(new SvelteSet(config.columns));

	// Sync SvelteSet → config.columns when selectedColumns changes
	$effect(() => {
		config.columns = Array.from(selectedColumns);
	});

	function toggleColumn(columnName: string) {
		if (selectedColumns.has(columnName)) {
			selectedColumns.delete(columnName);
		} else {
			selectedColumns.add(columnName);
		}
	}

	function selectAll() {
		selectedColumns = new SvelteSet(schema.columns.map((c) => c.name));
	}

	function deselectAll() {
		selectedColumns = new SvelteSet();
	}

	let selectedColumnNames = $derived(Array.from(selectedColumns));
</script>

<div class="select-config">
	<h3>Select Columns</h3>

	<div class="bulk-actions">
		<button type="button" onclick={selectAll}>Select All</button>
		<button type="button" onclick={deselectAll}>Deselect All</button>
	</div>

	<div class="column-list">
		{#each schema.columns as column (column.name)}
			<label class="column-item">
				<input
					type="checkbox"
					checked={selectedColumns.has(column.name)}
					onchange={() => toggleColumn(column.name)}
				/>
				<span class="column-name">{column.name}</span>
				<span class="column-type">({column.dtype})</span>
			</label>
		{/each}
	</div>

	{#if selectedColumnNames.length > 0}
		<div class="selected-summary">
			<strong>Selected ({selectedColumnNames.length}):</strong>
			<div class="selected-names">
				{selectedColumnNames.join(', ')}
			</div>
		</div>
	{/if}
</div>

<style>
	.select-config {
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	.bulk-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}

	.bulk-actions button {
		padding: 0.5rem 1rem;
		background-color: var(--fg-muted);
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.column-list {
		max-height: 300px;
		overflow-y: auto;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
		padding: 0.5rem;
		margin-bottom: 1rem;
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: 0.5rem;
		cursor: pointer;
		border-radius: 4px;
	}

	.column-item:hover {
		background-color: var(--bg-tertiary);
	}

	.column-item input[type='checkbox'] {
		margin-right: 0.5rem;
		cursor: pointer;
	}

	.column-name {
		font-weight: 500;
		margin-right: 0.5rem;
	}

	.column-type {
		color: var(--fg-muted);
		font-size: 0.875rem;
	}

	.selected-summary {
		padding: 1rem;
		background-color: var(--accent-bg);
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.selected-names {
		margin-top: 0.5rem;
		font-size: 0.875rem;
		color: var(--fg-primary);
	}

	button:hover {
		opacity: 0.9;
	}
</style>
