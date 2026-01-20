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

	// Keep SvelteSet for UI - initialize from config
	// eslint-disable-next-line svelte/no-unnecessary-state-wrap
	let selectedColumns = $state(new SvelteSet<string>(config?.columns ?? []));

	// Track if component has been initialized to avoid re-init on deselectAll
	let initialized = $state(false);

	// Track the config reference to detect when a different step is selected
	let prevConfig = $state(config);

	// Sync config.columns → SvelteSet when config changes (different step selected)
	$effect(() => {
		if (config !== prevConfig) {
			selectedColumns = new SvelteSet(safeColumns);
			prevConfig = config;
			initialized = true;
		}
	});

	// Initialize on first render only
	$effect(() => {
		if (!initialized && safeColumns.length > 0) {
			selectedColumns = new SvelteSet(safeColumns);
			initialized = true;
		}
	});

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
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		color: var(--panel-header-fg);
	}

	.bulk-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}

	.bulk-actions button {
		padding: 0.5rem 1rem;
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
		padding: 0.5rem;
		margin-bottom: 1rem;
		background-color: var(--bg-primary);
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: 0.5rem;
		cursor: pointer;
		border-radius: var(--radius-sm);
	}

	.column-item:hover {
		background-color: var(--bg-hover);
	}

	.column-item input[type='checkbox'] {
		margin-right: 0.5rem;
		cursor: pointer;
	}

	.column-name {
		font-weight: 500;
		margin-right: 0.5rem;
		color: var(--fg-primary);
	}

	.column-type {
		color: var(--fg-tertiary);
		font-size: 0.875rem;
	}

	.selected-summary {
		padding: 1rem;
		background-color: var(--info-bg);
		border: 1px solid var(--info-border);
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
		color: var(--info-fg);
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
