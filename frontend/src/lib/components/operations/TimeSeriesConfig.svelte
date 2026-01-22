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
		config?: TimeSeriesConfigData;
	}

	let {
		schema,
		config = $bindable({
			column: '',
			operation_type: 'extract',
			new_column: '',
			component: 'year',
			value: 1,
			unit: 'days',
			column2: ''
		})
	}: Props = $props();

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
</script>

<div class="timeseries-config">
	<h3>Time Series Configuration</h3>

	<div class="section">
		<h4>Source Column</h4>
		<select id="ts-column" bind:value={config.column}>
			<option value="">Select date/time column...</option>
			{#each dateColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
		{#if dateColumns.length === 0}
			<p class="warning">No date/time columns detected in schema</p>
		{/if}
	</div>

	<div class="section">
		<h4>Operation Type</h4>
		<select id="ts-operation" bind:value={config.operation_type}>
			{#each operations as op (op.value)}
				<option value={op.value}>{op.label}</option>
			{/each}
		</select>
	</div>

	{#if config.operation_type === 'extract'}
		<div class="section">
			<h4>Extract Component</h4>
			<select id="ts-component" bind:value={config.component}>
				{#each extractComponents as comp (comp)}
					<option value={comp}>{comp}</option>
				{/each}
			</select>
		</div>
	{:else if config.operation_type === 'add' || config.operation_type === 'subtract'}
		<div class="section">
			<h4>Time Period</h4>
			<div class="inline-group">
				<input id="ts-value" type="number" bind:value={config.value} min="0" />
				<select id="ts-unit" bind:value={config.unit}>
					{#each timeUnits as unit (unit)}
						<option value={unit}>{unit}</option>
					{/each}
				</select>
			</div>
		</div>
	{:else if config.operation_type === 'diff'}
		<div class="section">
			<h4>Second Date Column</h4>
			<select id="ts-column2" bind:value={config.column2}>
				<option value="">Select column...</option>
				{#each dateColumns as column (column.name)}
					<option value={column.name}>{column.name} ({column.dtype})</option>
				{/each}
			</select>
		</div>
	{/if}

	<div class="section">
		<h4>New Column Name</h4>
		<input id="ts-new-column" type="text" bind:value={config.new_column} placeholder="e.g., year, future_date" />
	</div>
</div>

<style>
	.timeseries-config {
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

	h4 {
		margin-top: 0;
		margin-bottom: 0.5rem;
		font-size: 1rem;
		color: var(--fg-secondary);
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: var(--form-section-bg);
		border-radius: var(--radius-md);
		border: 1px solid var(--form-section-border);
	}

	.warning {
		font-size: 0.875rem;
		color: var(--error-fg);
		margin-top: 0.5rem;
		margin-bottom: 0;
	}

	select,
	input[type='text'],
	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
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
</style>
