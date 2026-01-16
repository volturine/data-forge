<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface TimeSeriesConfigData {
		column: string;
		operation_type: string;
		new_column: string;
		component?: string;
		value?: number;
		unit?: string;
		column2?: string;
	}

	interface Props {
		schema: Schema;
		config: TimeSeriesConfigData;
		onSave: (config: TimeSeriesConfigData) => void;
	}

	let { schema, config, onSave }: Props = $props();

	let localConfig = $state<TimeSeriesConfigData>({
		column: config?.column || '',
		operation_type: config?.operation_type || 'extract',
		new_column: config?.new_column || '',
		component: config?.component || 'year',
		value: config?.value || 1,
		unit: config?.unit || 'days',
		column2: config?.column2 || ''
	});

	const operations = [
		{ value: 'extract', label: 'Extract Component' },
		{ value: 'add', label: 'Add Time Period' },
		{ value: 'subtract', label: 'Subtract Time Period' },
		{ value: 'diff', label: 'Date Difference' }
	];

	const extractComponents = [
		'year',
		'month',
		'day',
		'hour',
		'minute',
		'second',
		'quarter',
		'week',
		'dayofweek'
	];

	const timeUnits = ['seconds', 'minutes', 'hours', 'days', 'weeks'];

	const dateColumns = $derived(
		schema.columns.filter(
			(col) =>
				col.dtype.toLowerCase().includes('date') ||
				col.dtype.toLowerCase().includes('time') ||
				col.dtype.toLowerCase() === 'date' ||
				col.dtype.toLowerCase() === 'datetime'
		)
	);

	function handleSave() {
		const saveConfig: TimeSeriesConfigData = {
			column: localConfig.column,
			operation_type: localConfig.operation_type,
			new_column: localConfig.new_column
		};

		if (localConfig.operation_type === 'extract') {
			saveConfig.component = localConfig.component;
		} else if (
			localConfig.operation_type === 'add' ||
			localConfig.operation_type === 'subtract'
		) {
			saveConfig.value = localConfig.value;
			saveConfig.unit = localConfig.unit;
		} else if (localConfig.operation_type === 'diff') {
			saveConfig.column2 = localConfig.column2;
		}

		onSave(saveConfig);
	}

	function handleCancel() {
		localConfig = {
			column: config?.column || '',
			operation_type: config?.operation_type || 'extract',
			new_column: config?.new_column || '',
			component: config?.component || 'year',
			value: config?.value || 1,
			unit: config?.unit || 'days',
			column2: config?.column2 || ''
		};
	}
</script>

<div class="timeseries-config">
	<h3>Time Series Configuration</h3>

	<div class="section">
		<h4>Source Column</h4>
		<select bind:value={localConfig.column}>
			<option value="">Select date/time column...</option>
			{#each dateColumns as column}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
		{#if dateColumns.length === 0}
			<p class="warning">No date/time columns detected in schema</p>
		{/if}
	</div>

	<div class="section">
		<h4>Operation Type</h4>
		<select bind:value={localConfig.operation_type}>
			{#each operations as op}
				<option value={op.value}>{op.label}</option>
			{/each}
		</select>
	</div>

	{#if localConfig.operation_type === 'extract'}
		<div class="section">
			<h4>Extract Component</h4>
			<select bind:value={localConfig.component}>
				{#each extractComponents as comp}
					<option value={comp}>{comp}</option>
				{/each}
			</select>
			<p class="help-text">Extract year, month, day, etc. from the date column</p>
		</div>
	{:else if localConfig.operation_type === 'add' || localConfig.operation_type === 'subtract'}
		<div class="section">
			<h4>Time Period</h4>
			<div class="inline-group">
				<input type="number" bind:value={localConfig.value} min="0" />
				<select bind:value={localConfig.unit}>
					{#each timeUnits as unit}
						<option value={unit}>{unit}</option>
					{/each}
				</select>
			</div>
			<p class="help-text">
				{localConfig.operation_type === 'add' ? 'Add' : 'Subtract'}
				{localConfig.value}
				{localConfig.unit} to/from the date
			</p>
		</div>
	{:else if localConfig.operation_type === 'diff'}
		<div class="section">
			<h4>Second Date Column</h4>
			<select bind:value={localConfig.column2}>
				<option value="">Select column...</option>
				{#each dateColumns as column}
					<option value={column.name}>{column.name} ({column.dtype})</option>
				{/each}
			</select>
			<p class="help-text">Calculate difference: column2 - column (result in duration)</p>
		</div>
	{/if}

	<div class="section">
		<h4>New Column Name</h4>
		<input type="text" bind:value={localConfig.new_column} placeholder="e.g., year, future_date" />
	</div>

	<div class="actions">
		<button type="button" onclick={handleSave} class="save-btn" disabled={!localConfig.column || !localConfig.new_column}>
			Save
		</button>
		<button type="button" onclick={handleCancel} class="cancel-btn">Cancel</button>
	</div>
</div>

<style>
	.timeseries-config {
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

	.help-text {
		font-size: 0.875rem;
		color: #6c757d;
		margin-top: 0.5rem;
		margin-bottom: 0;
	}

	.warning {
		font-size: 0.875rem;
		color: #dc3545;
		margin-top: 0.5rem;
		margin-bottom: 0;
	}

	select,
	input[type='text'],
	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.inline-group {
		display: flex;
		gap: 0.5rem;
	}

	.inline-group input {
		flex: 1;
	}

	.inline-group select {
		flex: 1;
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
