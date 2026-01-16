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
		config: PivotConfigData;
		onSave: (config: PivotConfigData) => void;
	}

	let { schema, config, onSave }: Props = $props();

	let localConfig = $state<PivotConfigData>({
		index: config?.index ? [...config.index] : [],
		columns: config?.columns || '',
		values: config?.values || '',
		aggregate_function: config?.aggregate_function || 'first'
	});

	const aggregateFunctions = [
		'first',
		'last',
		'sum',
		'mean',
		'median',
		'min',
		'max',
		'count'
	];

	function toggleIndexColumn(columnName: string) {
		const index = localConfig.index.indexOf(columnName);
		if (index > -1) {
			localConfig.index.splice(index, 1);
		} else {
			localConfig.index.push(columnName);
		}
	}

	function handleSave() {
		onSave(localConfig);
	}

	function handleCancel() {
		localConfig = {
			index: config?.index ? [...config.index] : [],
			columns: config?.columns || '',
			values: config?.values || '',
			aggregate_function: config?.aggregate_function || 'first'
		};
	}
</script>

<div class="pivot-config">
	<h3>Pivot Configuration</h3>

	<div class="help-banner">
		Transform data from long to wide format. Select index columns (rows to keep), pivot column
		(spread into new columns), and values column (data to fill).
	</div>

	<div class="section">
		<h4>Index Columns (Group By)</h4>
		<div class="column-list">
			{#each schema.columns as column}
				<label class="column-item">
					<input
						type="checkbox"
						checked={localConfig.index.includes(column.name)}
						onchange={() => toggleIndexColumn(column.name)}
					/>
					<span>{column.name} ({column.dtype})</span>
				</label>
			{/each}
		</div>
		{#if localConfig.index.length > 0}
			<div class="selected-info">Selected: {localConfig.index.join(', ')}</div>
		{/if}
	</div>

	<div class="section">
		<h4>Pivot Column</h4>
		<p class="help-text">Column whose unique values will become new column names</p>
		<select bind:value={localConfig.columns}>
			<option value="">Select column...</option>
			{#each schema.columns as column}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="section">
		<h4>Values Column</h4>
		<p class="help-text">Column containing the data to populate the pivoted table</p>
		<select bind:value={localConfig.values}>
			<option value="">Select column...</option>
			{#each schema.columns as column}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="section">
		<h4>Aggregation Function</h4>
		<p class="help-text">How to combine multiple values in the same cell</p>
		<select bind:value={localConfig.aggregate_function}>
			{#each aggregateFunctions as func}
				<option value={func}>{func}</option>
			{/each}
		</select>
	</div>

	<div class="example">
		<strong>Example:</strong> Pivot sales data by date (index), product (columns), revenue (values)
		with sum aggregation
	</div>

	<div class="actions">
		<button
			type="button"
			onclick={handleSave}
			class="save-btn"
			disabled={!localConfig.columns || !localConfig.values || localConfig.index.length === 0}
		>
			Save
		</button>
		<button type="button" onclick={handleCancel} class="cancel-btn">Cancel</button>
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

	.help-banner {
		background-color: #e7f3ff;
		padding: 0.75rem;
		border-left: 3px solid #007bff;
		border-radius: 4px;
		margin-bottom: 1rem;
		font-size: 0.875rem;
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: #f8f9fa;
		border-radius: 4px;
	}

	.help-text {
		font-size: 0.875rem;
		color: #6c757d;
		margin-bottom: 0.5rem;
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

	.example {
		margin-bottom: 1rem;
		padding: 0.75rem;
		background-color: #fff3cd;
		border-left: 3px solid #ffc107;
		border-radius: 4px;
		font-size: 0.875rem;
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

	.save-btn:disabled {
		background-color: #ccc;
		cursor: not-allowed;
	}

	.cancel-btn {
		padding: 0.5rem 1.5rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
