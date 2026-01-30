<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { PivotConfigData } from '$lib/types/operation-config';

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

	<div class="field-group">
		<label for="pivot-column"
			>Pivot Column <span class="hint">(values become new columns)</span></label
		>
		<select id="pivot-column" bind:value={config.columns}>
			<option value="">Select column...</option>
			{#each schema.columns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
		<span id="pivot-column-help" class="hint"
			>Select the column whose unique values will become new columns</span
		>
	</div>

	<div class="field-group" role="group" aria-labelledby="index-columns-label">
		<span id="index-columns-label" class="group-label"
			>Index Columns <span class="hint">(rows)</span></span
		>
		<div class="checkbox-grid">
			{#each schema.columns as column (column.name)}
				<label class="checkbox-label">
					<input
						id={`pivot-checkbox-index-${column.name}`}
						data-testid={`pivot-index-checkbox-${column.name}`}
						type="checkbox"
						name="pivot-index"
						checked={safeIndex.includes(column.name)}
						onchange={() => toggleIndexColumn(column.name)}
						aria-label={`Include ${column.name} as index column`}
					/>
					<span>{column.name}</span>
				</label>
			{/each}
		</div>
		{#if safeIndex.length > 0}
			<div id="pivot-index-summary" class="selection-summary" aria-live="polite">
				{safeIndex.length} selected
			</div>
		{/if}
	</div>

	<div class="field-group">
		<label for="pivot-select-values">Values Column</label>
		<select id="pivot-select-values" data-testid="pivot-values-select" bind:value={config.values}>
			<option value="">All remaining columns</option>
			{#each schema.columns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="field-group">
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
		<div class="field-group">
			<button
				id="pivot-btn-refresh"
				data-testid="pivot-refresh-button"
				class="refresh-button"
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
			<p class="hint">Click to compute the resulting columns after pivot</p>
		</div>
	{/if}
</div>

<style>
	.field-group {
		margin-bottom: var(--space-4);
	}
	.hint {
		color: var(--fg-muted);
		font-size: var(--text-xs);
	}
	.checkbox-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
		gap: var(--space-2);
		padding: var(--space-2);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-secondary);
		max-height: 150px;
		overflow-y: auto;
	}
	.checkbox-label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-sm);
	}
	.checkbox-label:hover {
		background-color: var(--bg-hover);
	}
	.checkbox-label input {
		accent-color: var(--accent-primary);
	}
	.selection-summary {
		margin-top: var(--space-2);
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.refresh-button {
		width: 100%;
		padding: var(--space-2) var(--space-3);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		transition: all var(--transition);
	}
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
