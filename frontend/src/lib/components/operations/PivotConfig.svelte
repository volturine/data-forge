<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface PivotConfigData {
		index: string[];
		columns: string;
		values: string;
		aggregate_function: string;
	}

	interface Props {
		schema: Schema;
		config?: PivotConfigData;
	}

	let {
		schema,
		config = $bindable({ index: [], columns: '', values: '', aggregate_function: 'first' })
	}: Props = $props();

	// Ensure config has proper structure (handles empty {} from step creation)
	$effect(() => {
		if (!config || typeof config !== 'object') {
			config = { index: [], columns: '', values: '', aggregate_function: 'first' };
		} else {
			if (!Array.isArray(config.index)) {
				config.index = [];
			}
			if (typeof config.columns !== 'string') {
				config.columns = '';
			}
			if (typeof config.values !== 'string') {
				config.values = '';
			}
			if (typeof config.aggregate_function !== 'string') {
				config.aggregate_function = 'first';
			}
		}
	});

	// Safe accessor
	let safeIndex = $derived(Array.isArray(config?.index) ? config.index : []);

	const aggregateFunctions = ['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'count'];

	function toggleIndexColumn(columnName: string) {
		if (!Array.isArray(config.index)) {
			config.index = [];
		}
		const index = config.index.indexOf(columnName);
		if (index > -1) {
			config.index.splice(index, 1);
		} else {
			config.index.push(columnName);
		}
	}
</script>

<div class="pivot-config">
	<h3>Pivot Configuration</h3>

	<div class="section">
		<h4>Index Columns</h4>
		<div class="column-list">
			{#each schema.columns as column (column.name)}
				<label class="column-item">
					<input
						type="checkbox"
						checked={safeIndex.includes(column.name)}
						onchange={() => toggleIndexColumn(column.name)}
					/>
					<span>{column.name} ({column.dtype})</span>
				</label>
			{/each}
		</div>
		{#if safeIndex.length > 0}
			<div class="selected-info">Selected: {safeIndex.join(', ')}</div>
		{/if}
	</div>

	<div class="section">
		<h4>Pivot Column</h4>
		<select bind:value={config.columns}>
			<option value="">Select column...</option>
			{#each schema.columns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="section">
		<h4>Values Column</h4>
		<select bind:value={config.values}>
			<option value="">Select column...</option>
			{#each schema.columns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="section">
		<h4>Aggregation Function</h4>
		<select bind:value={config.aggregate_function}>
			{#each aggregateFunctions as func (func)}
				<option value={func}>{func}</option>
			{/each}
		</select>
	</div>
</div>

<style>
	.pivot-config {
		padding: 1rem;
		border: 1px solid #ddd;
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.5rem;
		font-size: 1rem;
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: #f8f9fa;
		border-radius: 4px;
	}

	.column-list {
		max-height: 200px;
		overflow-y: auto;
		border: 1px solid #ddd;
		border-radius: 4px;
		padding: 0.5rem;
		background-color: white;
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

	.selected-info {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: #e7f3ff;
		border-radius: 4px;
		font-size: 0.875rem;
	}

	select {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
