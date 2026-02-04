<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	const uid = $props.id();

	interface Aggregation {
		column: string;
		function: string;
		alias: string;
	}

	interface GroupByConfigData {
		groupBy: string[];
		aggregations: Aggregation[];
	}

	interface Props {
		schema: Schema;
		config?: GroupByConfigData;
	}

	let { schema, config = $bindable({ groupBy: [], aggregations: [] }) }: Props = $props();

	// Config now guaranteed to have proper structure
	let safeGroupBy = $derived(config.groupBy);
	let safeAggregations = $derived(config.aggregations);

	let newAggregation = $state<Aggregation>({
		column: '',
		function: 'sum',
		alias: ''
	});

	const aggregationFunctions = [
		'sum',
		'mean',
		'count',
		'min',
		'max',
		'first',
		'last',
		'median',
		'std',
		'collect_list',
		'collect_set'
	];

	function toggleGroupByColumn(columnName: string) {
		const index = safeGroupBy.indexOf(columnName);
		if (index > -1) {
			config.groupBy = safeGroupBy.filter((_, i) => i !== index);
		} else {
			config.groupBy = [...safeGroupBy, columnName];
		}
	}

	function addAggregation() {
		if (!newAggregation.column) return;

		const alias = newAggregation.alias || `${newAggregation.column}_${newAggregation.function}`;

		config.aggregations = [
			...safeAggregations,
			{
				column: newAggregation.column,
				function: newAggregation.function,
				alias
			}
		];

		newAggregation = {
			column: '',
			function: 'sum',
			alias: ''
		};
	}

	function removeAggregation(index: number) {
		config.aggregations = safeAggregations.filter((_, i) => i !== index);
	}
</script>

<div class="config-panel" role="region" aria-label="Group by configuration">
	<h3>Group By Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="{uid}-columns-heading">
		<h4 id="{uid}-columns-heading">Group By Columns</h4>
		<div class="column-list">
			{#each schema.columns as column (column.name)}
				<label class="column-item">
					<input
						id="{uid}-col-{column.name}"
						data-testid={`groupby-checkbox-${column.name}`}
						type="checkbox"
						checked={safeGroupBy.includes(column.name)}
						onchange={() => toggleGroupByColumn(column.name)}
						aria-label={`Group by ${column.name}`}
					/>
					<span class="column-name">{column.name}</span>
					<ColumnTypeBadge columnType={column.dtype} size="xs" />
				</label>
			{/each}
		</div>
		{#if safeGroupBy.length > 0}
			<div id="groupby-selected-info" class="info-box" aria-live="polite">
				Selected: {safeGroupBy.join(', ')}
			</div>
		{/if}
	</div>

	<div class="form-section" role="group" aria-labelledby="{uid}-agg-heading">
		<h4 id="{uid}-agg-heading">Aggregations</h4>

		<div class="add-aggregation" role="group" aria-label="Add aggregation form">
			<div class="agg-column-dropdown">
				<ColumnDropdown
					{schema}
					value={newAggregation.column}
					onChange={(val) => (newAggregation.column = val)}
					placeholder="Select column..."
				/>
			</div>

			<label for="{uid}-agg-function" class="sr-only">Aggregation function</label>
			<select
				id="{uid}-agg-function"
				data-testid="agg-function-select"
				bind:value={newAggregation.function}
			>
				{#each aggregationFunctions as func (func)}
					<option value={func}>{func}</option>
				{/each}
			</select>

			<input
				id="{uid}-agg-alias"
				type="text"
				bind:value={newAggregation.alias}
				placeholder="Alias (optional)"
			/>

			<button
				id="{uid}-agg-add"
				data-testid="agg-add-button"
				type="button"
				onclick={addAggregation}
				disabled={!newAggregation.column}
				aria-label="Add aggregation"
			>
				Add
			</button>
		</div>

		{#if safeAggregations.length > 0}
			<div
				id="aggregations-list"
				class="aggregations-list"
				role="list"
				aria-label="Configured aggregations"
			>
				{#each safeAggregations as agg, i (i)}
					<div class="aggregation-item" role="listitem">
						<span class="agg-details">
							{agg.function}({agg.column}) as {agg.alias}
						</span>
						<button
							id={`agg-btn-remove-${i}`}
							data-testid={`agg-remove-button-${i}`}
							type="button"
							onclick={() => removeAggregation(i)}
							aria-label={`Remove aggregation ${agg.alias}`}
						>
							Remove
						</button>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.add-aggregation {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
		flex-wrap: wrap;
	}
	.agg-column-dropdown {
		flex: 2;
		min-width: 160px;
	}
	.add-aggregation select {
		flex: 1;
		min-width: 120px;
	}
	.add-aggregation input {
		flex: 2;
		min-width: 160px;
	}
	.add-aggregation button {
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.add-aggregation button:disabled {
		background-color: var(--bg-muted);
		cursor: not-allowed;
		color: var(--fg-muted);
		border: 1px solid var(--border-secondary);
	}
	.aggregations-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.aggregation-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-3);
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
	}
	.agg-details {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--fg-primary);
	}
	.aggregation-item button {
		padding: var(--space-1) var(--space-3);
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-sm);
	}
	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
