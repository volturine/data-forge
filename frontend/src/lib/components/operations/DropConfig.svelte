<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { Previous } from 'runed';
	import { SvelteSet } from 'svelte/reactivity';

	interface DropConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: DropConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	// Ensure config has proper structure
	$effect(() => {
		if (!config || typeof config !== 'object') {
			config = { columns: [] };
		} else if (!Array.isArray(config.columns)) {
			config.columns = [];
		}
	});

	// Safe accessor
	let safeColumns = $derived(Array.isArray(config?.columns) ? config.columns : []);

	// Keep SvelteSet for UI
	// eslint-disable-next-line svelte/no-unnecessary-state-wrap
	let selectedColumns = $state(new SvelteSet<string>());

	// Track config changes with Previous utility
	const prevConfig = new Previous(() => config);

	// Sync config → SvelteSet when config changes
	$effect(() => {
		if (prevConfig.current !== config) {
			selectedColumns = new SvelteSet(safeColumns);
		}
	});

	// Initialize on first render
	$effect(() => {
		if (selectedColumns.size === 0 && safeColumns.length > 0) {
			selectedColumns = new SvelteSet(safeColumns);
		}
	});

	// Config is now updated directly in toggleColumn/selectAll/deselectAll functions
	// to avoid infinite loop from bidirectional effect binding

	function toggleColumn(columnName: string) {
		if (selectedColumns.has(columnName)) {
			selectedColumns.delete(columnName);
		} else {
			selectedColumns.add(columnName);
		}
		// Update config directly to avoid infinite loop
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
</div>

<style>
	.drop-config {
		padding: var(--space-4);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: var(--space-2);
		color: var(--panel-header-fg);
	}

	.description {
		margin-top: 0;
		margin-bottom: var(--space-4);
		color: var(--fg-tertiary);
		font-size: var(--text-sm);
	}

	.bulk-actions {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
		flex-wrap: wrap;
	}

	.bulk-actions button {
		padding: var(--space-2) var(--space-4);
		background-color: var(--bg-tertiary);
		color: var(--fg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.column-list {
		max-height: 300px;
		overflow-y: auto;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		margin-bottom: var(--space-4);
		background-color: var(--bg-primary);
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: var(--space-2);
		cursor: pointer;
		border-radius: var(--radius-sm);
	}

	.column-item:hover {
		background-color: var(--bg-hover);
	}

	.column-item input[type='checkbox'] {
		margin-right: var(--space-2);
		cursor: pointer;
	}

	.column-name {
		font-weight: var(--font-medium);
		margin-right: var(--space-2);
		color: var(--fg-primary);
	}

	.column-type {
		color: var(--fg-tertiary);
		font-size: var(--text-sm);
	}

	.selected-summary {
		padding: var(--space-4);
		background-color: var(--warning-bg);
		border: 1px solid var(--warning-border);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-4);
		color: var(--warning-fg);
	}

	.selected-names {
		margin-top: var(--space-2);
		font-size: var(--text-sm);
		color: var(--fg-primary);
	}

	.warning-box {
		padding: var(--space-4);
		background-color: var(--panel-muted-bg);
		border: 1px solid var(--panel-muted-border);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-4);
		color: var(--fg-tertiary);
	}

	button:hover {
		opacity: 0.9;
	}
</style>
