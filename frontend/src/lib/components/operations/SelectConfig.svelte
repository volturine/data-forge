<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface SelectConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: SelectConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	function toggleColumn(columnName: string) {
		const cols = config.columns;
		const index = cols.indexOf(columnName);
		if (index > -1) {
			config.columns = cols.filter((_, i) => i !== index);
		} else {
			config.columns = [...cols, columnName];
		}
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
					checked={config.columns.includes(column.name)}
					onchange={() => toggleColumn(column.name)}
					aria-label={`Select column ${column.name}`}
				/>
				<span class="column-name">{column.name}</span>
				<span class="column-type">({column.dtype})</span>
			</label>
		{/each}
	</div>

	{#if config.columns.length > 0}
		<div id="select-summary-selected" class="selected-summary" aria-live="polite">
			<strong>Selected ({config.columns.length}):</strong>
			<div class="selected-names">
				{config.columns.join(', ')}
			</div>
		</div>
	{/if}
</div>
