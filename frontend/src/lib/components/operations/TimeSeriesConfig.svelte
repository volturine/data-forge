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

<div class="timeseries-config" role="region" aria-label="Time series configuration">
	<h3>Time Series Configuration</h3>

	<div class="section" role="group" aria-labelledby="ts-source-column-heading">
		<h4 id="ts-source-column-heading">Source Column</h4>
		<label for="ts-select-column" class="sr-only">Select date/time column</label>
		<select id="ts-select-column" data-testid="ts-column-select" bind:value={config.column}>
			<option value="">Select date/time column...</option>
			{#each dateColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
		{#if dateColumns.length === 0}
			<p id="ts-no-columns-warning" class="warning" role="alert">
				No date/time columns detected in schema
			</p>
		{/if}
	</div>

	<div class="section" role="group" aria-labelledby="ts-operation-heading">
		<h4 id="ts-operation-heading">Operation Type</h4>
		<label for="ts-select-operation" class="sr-only">Select operation type</label>
		<select
			id="ts-select-operation"
			data-testid="ts-operation-select"
			bind:value={config.operation_type}
		>
			{#each operations as op (op.value)}
				<option value={op.value}>{op.label}</option>
			{/each}
		</select>
	</div>

	{#if config.operation_type === 'extract'}
		<div class="section" role="group" aria-labelledby="ts-component-heading">
			<h4 id="ts-component-heading">Extract Component</h4>
			<label for="ts-select-component" class="sr-only">Select component to extract</label>
			<select
				id="ts-select-component"
				data-testid="ts-component-select"
				bind:value={config.component}
			>
				{#each extractComponents as comp (comp)}
					<option value={comp}>{comp}</option>
				{/each}
			</select>
		</div>
	{:else if config.operation_type === 'add' || config.operation_type === 'subtract'}
		<div class="section" role="group" aria-labelledby="ts-period-heading">
			<h4 id="ts-period-heading">Time Period</h4>
			<div class="inline-group">
				<div class="input-group">
					<label for="ts-input-value">Value:</label>
					<input
						id="ts-input-value"
						data-testid="ts-value-input"
						type="number"
						bind:value={config.value}
						min="0"
						aria-label="Time period value"
					/>
				</div>
				<div class="input-group">
					<label for="ts-select-unit">Unit:</label>
					<select id="ts-select-unit" data-testid="ts-unit-select" bind:value={config.unit}>
						{#each timeUnits as unit (unit)}
							<option value={unit}>{unit}</option>
						{/each}
					</select>
				</div>
			</div>
		</div>
	{:else if config.operation_type === 'diff'}
		<div class="section" role="group" aria-labelledby="ts-column2-heading">
			<h4 id="ts-column2-heading">Second Date Column</h4>
			<label for="ts-select-column2" class="sr-only">Select second date column</label>
			<select id="ts-select-column2" data-testid="ts-column2-select" bind:value={config.column2}>
				<option value="">Select column...</option>
				{#each dateColumns as column (column.name)}
					<option value={column.name}>{column.name} ({column.dtype})</option>
				{/each}
			</select>
		</div>
	{/if}

	<div class="section" role="group" aria-labelledby="ts-new-column-heading">
		<h4 id="ts-new-column-heading">New Column Name</h4>
		<label for="ts-input-new-column" class="sr-only">New column name</label>
		<input
			id="ts-input-new-column"
			data-testid="ts-new-column-input"
			type="text"
			bind:value={config.new_column}
			placeholder="e.g., year, future_date"
		/>
	</div>
</div>

<style>
	.timeseries-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	.input-group {
		flex: 1;
	}

	.input-group label {
		display: block;
		font-size: 0.875rem;
		margin-bottom: 0.25rem;
		color: var(--fg-secondary);
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
