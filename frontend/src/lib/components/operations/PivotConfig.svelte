<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { PivotConfigData } from '$lib/types/operation-config';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	interface Props {
		schema: Schema;
		config?: PivotConfigData;
		onRefreshSchema?: () => void;
		isRefreshing?: boolean;
	}

	let {
		schema,
		config = $bindable({ index: [], columns: '', values: '', aggregate_function: 'first' }),
		onRefreshSchema,
		isRefreshing = false
	}: Props = $props();

	// Check if config is valid for schema refresh
	let isConfigValid = $derived(
		!!(config?.columns && Array.isArray(config?.index) && config.index.length > 0)
	);

	// Safe accessor
	let safeIndex = $derived(Array.isArray(config?.index) ? config.index : []);

	const aggregateFunctions = ['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'count'];

	function toggleIndexColumn(columnName: string) {
		const base = Array.isArray(config.index) ? config.index : [];
		const idx = base.indexOf(columnName);
		if (idx > -1) {
			config.index = base.filter((_, i) => i !== idx);
		} else {
			config.index = [...base, columnName];
		}
	}
</script>

<div class="config-panel" role="region" aria-label="Pivot configuration">
	<h3>Pivot Configuration</h3>

	<div class="mb-4">
		<label for="pivot-column"
			>Pivot Column <span class="text-xs" style="color: var(--fg-muted);"
				>(values become new columns)</span
			></label
		>
		<ColumnDropdown
			{schema}
			value={config.columns ?? ''}
			onChange={(val) => (config.columns = val)}
			placeholder="Select column..."
		/>
		<span id="pivot-column-help" class="text-xs" style="color: var(--fg-muted);"
			>Select the column whose unique values will become new columns</span
		>
	</div>

	<div class="mb-4" role="group" aria-labelledby="index-columns-label">
		<span id="index-columns-label" class="group-label"
			>Index Columns <span class="text-xs" style="color: var(--fg-muted);">(rows)</span></span
		>
		<div
			class="grid gap-2 p-2 rounded-sm max-h-[150px] overflow-y-auto"
			style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); border: 1px solid var(--border-primary); background-color: var(--bg-secondary);"
		>
			{#each schema.columns as column (column.name)}
				<label
					class="checkbox-label flex items-center gap-2 px-2 py-1 rounded-sm cursor-pointer text-sm hover:bg-[var(--bg-hover)]"
				>
					<input
						id={`pivot-checkbox-index-${column.name}`}
						data-testid={`pivot-index-checkbox-${column.name}`}
						type="checkbox"
						name="pivot-index"
						style="accent-color: var(--accent-primary);"
						checked={safeIndex.includes(column.name)}
						onchange={() => toggleIndexColumn(column.name)}
						aria-label={`Include ${column.name} as index column`}
					/>
					<span>{column.name}</span>
				</label>
			{/each}
		</div>
		{#if safeIndex.length > 0}
			<div
				id="pivot-index-summary"
				class="mt-2 text-xs"
				style="color: var(--fg-muted);"
				aria-live="polite"
			>
				{safeIndex.length} selected
			</div>
		{/if}
	</div>

	<div class="mb-4">
		<label for="pivot-select-values">Values Column</label>
		<ColumnDropdown
			{schema}
			value={config.values ?? ''}
			onChange={(val) => (config.values = val)}
			placeholder="All remaining columns"
		/>
	</div>

	<div class="mb-4">
		<label for="pivot-select-agg">Aggregation</label>
		<select
			id="pivot-select-agg"
			data-testid="pivot-agg-select"
			bind:value={config.aggregate_function}
		>
			{#each aggregateFunctions as func (func)}
				<option value={func}>{func}</option>
			{/each}
		</select>
	</div>

	{#if onRefreshSchema}
		<div class="mb-4">
			<button
				id="pivot-btn-refresh"
				data-testid="pivot-refresh-button"
				class="refresh-button w-full py-2 px-3 border-none rounded-sm text-sm font-medium cursor-pointer flex items-center justify-center gap-2 transition-all"
				style="background-color: var(--accent-primary); color: var(--bg-primary);"
				onclick={onRefreshSchema}
				disabled={!isConfigValid || isRefreshing}
				type="button"
				aria-busy={isRefreshing}
			>
				{#if isRefreshing}
					<span class="spinner" aria-hidden="true"></span>
					Refreshing...
				{:else}
					Refresh Output Columns
				{/if}
			</button>
			<p class="text-xs mt-1" style="color: var(--fg-muted);">
				Click to compute the resulting columns after pivot
			</p>
		</div>
	{/if}
</div>

<style>
	.refresh-button:hover:not(:disabled) {
		opacity: 0.9;
	}
	.refresh-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.refresh-button .spinner {
		width: 14px;
		height: 14px;
		border: 2px solid currentColor;
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
</style>
