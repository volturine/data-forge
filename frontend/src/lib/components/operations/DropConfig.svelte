<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { SvelteSet } from 'svelte/reactivity';

	interface DropConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config: DropConfigData;
		onSave: (config: DropConfigData) => void;
	}

	let { schema, config, onSave }: Props = $props();

	let selectedColumns = $state(new SvelteSet(config?.columns || []));

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

	function handleSave() {
		onSave({ columns: Array.from(selectedColumns) });
	}

	function handleCancel() {
		selectedColumns = new SvelteSet(config?.columns || []);
	}

	let selectedColumnNames = $derived(Array.from(selectedColumns));
</script>

<div class="drop-config">
	<h3>Drop Columns</h3>

	<p class="description">Select the columns you want to drop (remove) from the dataset.</p>

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
			<strong>Columns to Drop ({selectedColumnNames.length}):</strong>
			<div class="selected-names">
				{selectedColumnNames.join(', ')}
			</div>
		</div>
	{:else}
		<div class="warning-box">
			<strong>Warning:</strong> No columns selected. This operation will have no effect.
		</div>
	{/if}

	<div class="actions">
		<button type="button" onclick={handleSave} class="save-btn">Save</button>
		<button type="button" onclick={handleCancel} class="cancel-btn">Cancel</button>
	</div>
</div>

<style>
	.drop-config {
		padding: 1rem;
		border: 1px solid #ddd;
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 0.5rem;
	}

	.description {
		margin-top: 0;
		margin-bottom: 1rem;
		color: #6c757d;
		font-size: 0.875rem;
	}

	.bulk-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}

	.bulk-actions button {
		padding: 0.5rem 1rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.column-list {
		max-height: 300px;
		overflow-y: auto;
		border: 1px solid #ddd;
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
		background-color: #f8f9fa;
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
		color: #6c757d;
		font-size: 0.875rem;
	}

	.selected-summary {
		padding: 1rem;
		background-color: #fff3cd;
		border: 1px solid #ffc107;
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.selected-names {
		margin-top: 0.5rem;
		font-size: 0.875rem;
		color: #495057;
	}

	.warning-box {
		padding: 1rem;
		background-color: #f8f9fa;
		border: 1px solid #dee2e6;
		border-radius: 4px;
		margin-bottom: 1rem;
		color: #6c757d;
	}

	.actions {
		display: flex;
		gap: 0.5rem;
	}

	.save-btn {
		padding: 0.5rem 1.5rem;
		background-color: #007bff;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.cancel-btn {
		padding: 0.5rem 1.5rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	button:hover {
		opacity: 0.9;
	}
</style>
