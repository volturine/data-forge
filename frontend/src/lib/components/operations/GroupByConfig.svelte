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
		'std',
		'collect_list',
		'collect_set'
	];

	function toggleGroupByColumn(columnName: string) {
		const base = Array.isArray(config.groupBy) ? config.groupBy : [];
		const index = base.indexOf(columnName);
		if (index > -1) {
			config.groupBy = base.filter((_, i) => i !== index);
		} else {
			config.groupBy = [...base, columnName];
		}
	}

	function addAggregation() {
		if (!newAggregation.column) return;

		const base = Array.isArray(config.aggregations) ? config.aggregations : [];
		const alias = newAggregation.alias || `${newAggregation.column}_${newAggregation.function}`;

		config.aggregations = [
			...base,
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
		if (Array.isArray(config.aggregations)) {
			config.aggregations = config.aggregations.filter((_, i) => i !== index);
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
			<select id="agg-column" bind:value={newAggregation.column}>
				<option value="">Select column...</option>
				{#each schema.columns as column (column.name)}
					<option value={column.name}>{column.name} ({column.dtype})</option>
				{/each}
			</select>

			<select id="agg-function" bind:value={newAggregation.function}>
				{#each aggregationFunctions as func (func)}
					<option value={func}>{func}</option>
				{/each}
			</select>

			<input id="agg-alias" type="text" bind:value={newAggregation.alias} placeholder="Alias (optional)" />

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
		padding: var(--space-4);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: var(--space-4);
		color: var(--panel-header-fg);
	}

	h4 {
		margin-top: 0;
		margin-bottom: var(--space-3);
		font-size: var(--text-base);
		color: var(--fg-secondary);
	}

	.section {
		margin-bottom: var(--space-6);
		padding: var(--space-4);
		background-color: var(--form-section-bg);
		border-radius: var(--radius-md);
		border: 1px solid var(--form-section-border);
	}

	.column-list {
		max-height: 200px;
		overflow-y: auto;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		background-color: var(--bg-primary);
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: var(--space-2);
		cursor: pointer;
		border-radius: var(--radius-sm);
	}

	.column-item:hover {
		background-color: var(--bg-hover);
	}

	.column-item input[type='checkbox'] {
		margin-right: var(--space-2);
		cursor: pointer;
	}

	.selected-info {
		margin-top: var(--space-2);
		padding: var(--space-2);
		background-color: var(--info-bg);
		border: 1px solid var(--info-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		color: var(--info-fg);
	}

	.add-aggregation {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
		flex-wrap: wrap;
	}

	.add-aggregation select,
	.add-aggregation input {
		padding: var(--space-2);
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
