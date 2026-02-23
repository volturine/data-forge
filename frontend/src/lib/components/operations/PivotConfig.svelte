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
	const isConfigValid = $derived(
		!!(config?.columns && Array.isArray(config?.index) && config.index.length > 0)
	);

	// Safe accessor
	const safeIndex = $derived(Array.isArray(config?.index) ? config.index : []);

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
	<div class="mb-5">
		<label for="pivot-column"
			>Pivot Column <span class="text-xs text-fg-muted">(values become new columns)</span></label
		>
		<ColumnDropdown
			{schema}
			value={config.columns ?? ''}
			onChange={(val) => (config.columns = val)}
			placeholder="Select column..."
		/>
		<span id="pivot-column-help" class="text-xs text-fg-muted"
			>Select the column whose unique values will become new columns</span
		>
	</div>

	<div class="mb-5" role="group" aria-labelledby="index-columns-label">
		<span id="index-columns-label" class="group-label"
			>Index Columns <span class="text-xs text-fg-muted">(rows)</span></span
		>
		<div class="chip-grid grid gap-3 p-2 max-h-37.5 overflow-y-auto">
			{#each schema.columns as column (column.name)}
				<label
					class="checkbox-label flex items-center gap-3 px-2 py-1 cursor-pointer text-sm hover:bg-hover"
				>
					<input
						id={`pivot-checkbox-index-${column.name}`}
						data-testid={`pivot-index-checkbox-${column.name}`}
						type="checkbox"
						name="pivot-index"
						class="accent-primary"
						checked={safeIndex.includes(column.name)}
						onchange={() => toggleIndexColumn(column.name)}
						aria-label={`Include ${column.name} as index column`}
					/>
					<span>{column.name}</span>
				</label>
			{/each}
		</div>
		{#if safeIndex.length > 0}
			<div id="pivot-index-summary" class="mt-2 text-xs text-fg-muted" aria-live="polite">
				{safeIndex.length} selected
			</div>
		{/if}
	</div>

	<div class="mb-5">
		<label for="pivot-select-values">Values Column</label>
		<ColumnDropdown
			{schema}
			value={config.values ?? ''}
			onChange={(val) => (config.values = val)}
			placeholder="All remaining columns"
		/>
	</div>

	<div class="mb-5">
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
		<div class="mb-5">
			<button
				id="pivot-btn-refresh"
				data-testid="pivot-refresh-button"
				class="w-full py-2 px-3 border-none text-sm font-medium cursor-pointer flex items-center justify-center gap-2 accent-btn hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
				onclick={onRefreshSchema}
				disabled={!isConfigValid || isRefreshing}
				type="button"
				aria-busy={isRefreshing}
			>
				{#if isRefreshing}
					<span
						class="h-3.5 w-3.5 border-2 border-current border-t-transparent animate-spin"
						aria-hidden="true"
					></span>
					Refreshing...
				{:else}
					Refresh Output Columns
				{/if}
			</button>
			<p class="text-xs mt-1 text-fg-muted">Click to compute the resulting columns after pivot</p>
		</div>
	{/if}
</div>
