<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

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
		{ value: 'timestamp', label: 'Convert to Timestamp' },
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

	const timestampUnits = ['ns', 'us', 'ms'];

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

<div class="config-panel" role="region" aria-label="Time series configuration">
	<h3>Time Series Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="ts-source-column-heading">
		<h4 id="ts-source-column-heading">Source Column</h4>
		<ColumnDropdown
			{schema}
			value={config.column ?? ''}
			onChange={(val) => (config.column = val)}
			placeholder="Select date/time column..."
			filter={(col) =>
				col.dtype.toLowerCase().includes('date') ||
				col.dtype.toLowerCase().includes('time') ||
				col.dtype.toLowerCase() === 'date' ||
				col.dtype.toLowerCase() === 'datetime'}
		/>
		{#if dateColumns.length === 0}
			<p id="ts-no-columns-warning" class="warning-box" role="alert">
				No date/time columns detected in schema
			</p>
		{/if}
	</div>

	<div class="form-section" role="group" aria-labelledby="ts-operation-heading">
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
		<div class="form-section" role="group" aria-labelledby="ts-component-heading">
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
	{:else if config.operation_type === 'timestamp'}
		<div class="form-section" role="group" aria-labelledby="ts-timestamp-unit-heading">
			<h4 id="ts-timestamp-unit-heading">Timestamp Unit</h4>
			<label for="ts-select-timestamp-unit" class="sr-only">Select timestamp time unit</label>
			<select
				id="ts-select-timestamp-unit"
				data-testid="ts-timestamp-unit-select"
				bind:value={config.unit}
			>
				{#each timestampUnits as unit (unit)}
					<option value={unit}
						>{unit} ({unit === 'ns'
							? 'nanoseconds'
							: unit === 'us'
								? 'microseconds'
								: 'milliseconds'})</option
					>
				{/each}
			</select>
			<p class="help-text">Convert datetime to integer timestamp in the specified time unit.</p>
		</div>
	{:else if config.operation_type === 'add' || config.operation_type === 'subtract'}
		<div class="form-section" role="group" aria-labelledby="ts-period-heading">
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
		<div class="form-section" role="group" aria-labelledby="ts-column2-heading">
			<h4 id="ts-column2-heading">Second Date Column</h4>
			<ColumnDropdown
				{schema}
				value={config.column2 ?? ''}
				onChange={(val) => (config.column2 = val)}
				placeholder="Select column..."
				filter={(col) =>
					col.dtype.toLowerCase().includes('date') ||
					col.dtype.toLowerCase().includes('time') ||
					col.dtype.toLowerCase() === 'date' ||
					col.dtype.toLowerCase() === 'datetime'}
			/>
		</div>
	{/if}

	<div class="form-section" role="group" aria-labelledby="ts-new-column-heading">
		<h4 id="ts-new-column-heading">New Column Name</h4>
		<label for="ts-input-new-column" class="sr-only">New column name</label>
		<input
			id="ts-new-column"
			type="text"
			bind:value={config.new_column}
			placeholder="e.g., year, future_date"
		/>
	</div>
</div>

<style>
	.warning-box {
		font-size: var(--text-sm);
		color: var(--error-fg);
		margin-top: var(--space-2);
		margin-bottom: 0;
	}
	.help-text {
		font-size: var(--text-sm);
		color: var(--fg-muted);
		margin-top: var(--space-2);
		margin-bottom: 0;
	}
	.input-group {
		flex: 1;
	}
	.input-group label {
		display: block;
		font-size: var(--text-sm);
		margin-bottom: var(--space-1);
		color: var(--fg-secondary);
	}
	.inline-group {
		display: flex;
		gap: var(--space-2);
	}
	.inline-group input,
	.inline-group select {
		flex: 1;
	}
</style>
