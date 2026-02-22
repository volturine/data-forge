<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

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
</script>

<div class="config-panel" role="region" aria-label="Fill null configuration">
	<div class="form-section" role="group" aria-labelledby="fill-strategy-heading">
		<h4 id="fill-strategy-heading">Fill Strategy</h4>
		<label for="fill-select-strategy" class="sr-only">Select fill strategy</label>
		<select
			id="fill-select-strategy"
			data-testid="fill-strategy-select"
			bind:value={config.strategy}
			class="mb-2 w-full"
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
				class="mb-2 w-full"
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
		<MultiSelectColumnDropdown
			{schema}
			value={config.columns ?? []}
			onChange={(val) => (config.columns = val)}
			showSelectAll={true}
			placeholder="Select target columns..."
		/>

		{#if !config.columns || config.columns.length === 0}
			<div id="fill-no-columns-info" class="info-box">
				No columns selected - will apply to all columns
			</div>
		{/if}
	</div>
</div>
