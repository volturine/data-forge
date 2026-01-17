<script lang="ts">
	import type { Schema } from '$lib/types/schema';

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

	// Ensure config has proper structure (handles empty {} from step creation)
	$effect(() => {
		if (!config || typeof config !== 'object') {
			config = { groupBy: [], aggregations: [] };
		} else {
			if (!Array.isArray(config.groupBy)) {
				config.groupBy = [];
			}
			if (!Array.isArray(config.aggregations)) {
				config.aggregations = [];
			}
		}
	});

	// Safe accessors
	let safeGroupBy = $derived(Array.isArray(config?.groupBy) ? config.groupBy : []);
	let safeAggregations = $derived(Array.isArray(config?.aggregations) ? config.aggregations : []);

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
		'std'
	];

	function toggleGroupByColumn(columnName: string) {
		if (!Array.isArray(config.groupBy)) {
			config.groupBy = [];
		}
		const index = config.groupBy.indexOf(columnName);
		if (index > -1) {
			config.groupBy.splice(index, 1);
		} else {
			config.groupBy.push(columnName);
		}
	}

	function addAggregation() {
		if (!newAggregation.column) return;

		if (!Array.isArray(config.aggregations)) {
			config.aggregations = [];
		}

		const alias = newAggregation.alias || `${newAggregation.column}_${newAggregation.function}`;

		config.aggregations.push({
			column: newAggregation.column,
			function: newAggregation.function,
			alias
		});

		newAggregation = {
			column: '',
			function: 'sum',
			alias: ''
		};
	}

	function removeAggregation(index: number) {
		if (Array.isArray(config.aggregations)) {
			config.aggregations.splice(index, 1);
		}
	}
</script>

<div class="groupby-config">
	<h3>Group By Configuration</h3>

	<div class="section">
		<h4>Group By Columns</h4>
		<div class="column-list">
			{#each schema.columns as column (column.name)}
				<label class="column-item">
					<input
						type="checkbox"
						checked={safeGroupBy.includes(column.name)}
						onchange={() => toggleGroupByColumn(column.name)}
					/>
					<span>{column.name} ({column.dtype})</span>
				</label>
			{/each}
		</div>
		{#if safeGroupBy.length > 0}
			<div class="selected-info">
				Selected: {safeGroupBy.join(', ')}
			</div>
		{/if}
	</div>

	<div class="section">
		<h4>Aggregations</h4>

		<div class="add-aggregation">
			<select bind:value={newAggregation.column}>
				<option value="">Select column...</option>
				{#each schema.columns as column (column.name)}
					<option value={column.name}>{column.name} ({column.dtype})</option>
				{/each}
			</select>

			<select bind:value={newAggregation.function}>
				{#each aggregationFunctions as func (func)}
					<option value={func}>{func}</option>
				{/each}
			</select>

			<input type="text" bind:value={newAggregation.alias} placeholder="Alias (optional)" />

			<button type="button" onclick={addAggregation} disabled={!newAggregation.column}>
				Add
			</button>
		</div>

		{#if safeAggregations.length > 0}
			<div class="aggregations-list">
				{#each safeAggregations as agg, i (i)}
					<div class="aggregation-item">
						<span class="agg-details">
							{agg.function}({agg.column}) as {agg.alias}
						</span>
						<button type="button" onclick={() => removeAggregation(i)}>Remove</button>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.groupby-config {
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
		margin-bottom: 0.75rem;
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

	.column-list {
		max-height: 200px;
		overflow-y: auto;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: 0.5rem;
		background-color: var(--bg-primary);
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: 0.5rem;
		cursor: pointer;
		border-radius: var(--radius-sm);
	}

	.column-item:hover {
		background-color: var(--bg-hover);
	}

	.column-item input[type='checkbox'] {
		margin-right: 0.5rem;
		cursor: pointer;
	}

	.selected-info {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: var(--info-bg);
		border: 1px solid var(--info-border);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
		color: var(--info-fg);
	}

	.add-aggregation {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}

	.add-aggregation select,
	.add-aggregation input {
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.add-aggregation select:first-child {
		flex: 2;
		min-width: 160px;
	}

	.add-aggregation select:nth-child(2) {
		flex: 1;
		min-width: 120px;
	}

	.add-aggregation input {
		flex: 2;
		min-width: 160px;
	}

	.add-aggregation button {
		padding: 0.5rem 1rem;
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
		gap: 0.5rem;
	}

	.aggregation-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
	}

	.agg-details {
		font-family: var(--font-mono);
		font-size: 0.875rem;
		color: var(--fg-primary);
	}

	.aggregation-item button {
		padding: 0.25rem 0.75rem;
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.875rem;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
