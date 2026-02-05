<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';

	interface FillNullConfigData {
		strategy: string;
		columns: string[] | null;
		value?: string | number;
		value_type?: string;
	}

	interface Props {
		schema: Schema;
		config?: FillNullConfigData;
	}

	let {
		schema,
		config = $bindable({ strategy: 'literal', columns: null, value: '', value_type: 'Utf8' })
	}: Props = $props();

	const strategies = [
		{ value: 'literal', label: 'Fill with Value', needsValue: true, needsColumns: true },
		{ value: 'forward', label: 'Forward Fill', needsValue: false, needsColumns: true },
		{ value: 'backward', label: 'Backward Fill', needsValue: false, needsColumns: true },
		{ value: 'mean', label: 'Fill with Mean', needsValue: false, needsColumns: true },
		{ value: 'median', label: 'Fill with Median', needsValue: false, needsColumns: true },
		{ value: 'drop_rows', label: 'Drop Rows with Nulls', needsValue: false, needsColumns: true }
	];

	const currentStrategy = $derived(strategies.find((s) => s.value === config.strategy));

	function toggleColumn(columnName: string) {
		const base = config.columns ?? [];
		const index = base.indexOf(columnName);
		if (index > -1) {
			config.columns = base.filter((_, i) => i !== index);
		} else {
			config.columns = [...base, columnName];
		}
	}

	function selectAllColumns() {
		config.columns = schema.columns.map((c) => c.name);
	}

	function deselectAllColumns() {
		config.columns = [];
	}
</script>

<div class="config-panel" role="region" aria-label="Fill null configuration">
	<h3>Fill Null Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="fill-strategy-heading">
		<h4 id="fill-strategy-heading">Fill Strategy</h4>
		<label for="fill-select-strategy" class="sr-only">Select fill strategy</label>
		<select
			id="fill-select-strategy"
			data-testid="fill-strategy-select"
			bind:value={config.strategy}
		>
			{#each strategies as strategy (strategy.value)}
				<option value={strategy.value}>{strategy.label}</option>
			{/each}
		</select>
	</div>

	{#if currentStrategy?.needsValue}
		<div class="form-section" role="group" aria-labelledby="fill-value-heading">
			<h4 id="fill-value-heading">Fill Value</h4>
			<label for="fill-input-value" class="sr-only">Fill value</label>
			<input
				id="fill-value"
				type="text"
				bind:value={config.value}
				placeholder="Enter value (e.g., 0, N/A)"
			/>
			<ColumnTypeDropdown
				value={config.value_type ?? 'Utf8'}
				onChange={(val) => (config.value_type = val)}
				placeholder="Select type..."
			/>
		</div>
	{/if}

	<div class="form-section" role="group" aria-labelledby="target-columns-heading">
		<h4 id="target-columns-heading">Target Columns</h4>
		<div class="bulk-actions">
			<button
				id="fill-btn-select-all"
				data-testid="fill-select-all-button"
				type="button"
				onclick={selectAllColumns}
				aria-label="Select all columns"
			>
				Select All
			</button>
			<button
				id="fill-btn-deselect-all"
				data-testid="fill-deselect-all-button"
				type="button"
				onclick={deselectAllColumns}
				aria-label="Deselect all columns"
			>
				Deselect All
			</button>
		</div>

		<div id="fill-column-list" class="column-list" role="group" aria-label="Available columns">
			{#each schema.columns as column (column.name)}
				<label class="column-item">
					<input
						id={`fill-checkbox-${column.name}`}
						data-testid={`fill-column-checkbox-${column.name}`}
						type="checkbox"
						checked={config.columns?.includes(column.name) || false}
						onchange={() => toggleColumn(column.name)}
						aria-label={`Fill nulls in ${column.name}`}
					/>
					<span class="column-name">{column.name}</span>
					<ColumnTypeBadge columnType={column.dtype} size="xs" />
				</label>
			{/each}
		</div>

		{#if config.columns && config.columns.length > 0}
			<div id="fill-selected-info" class="info-box" aria-live="polite">
				Selected {config.columns.length} column{config.columns.length !== 1 ? 's' : ''}:
				{config.columns.join(', ')}
			</div>
		{:else}
			<div id="fill-no-columns-info" class="info-box">
				No columns selected - will apply to all columns
			</div>
		{/if}
	</div>
</div>

<style>
	select,
	input[type='text'] {
		width: 100%;
		margin-bottom: var(--space-2);
	}
</style>
