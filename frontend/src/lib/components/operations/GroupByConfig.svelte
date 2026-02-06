<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

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

	const safeGroupBy = $derived(config.groupBy ?? []);
	const safeAggregations = $derived(config.aggregations ?? []);

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
		<MultiSelectColumnDropdown
			{schema}
			value={config.groupBy ?? []}
			onChange={(val) => (config.groupBy = val)}
			showSelectAll={false}
			placeholder="Select group by columns..."
		/>
	</div>

	<div class="form-section" role="group" aria-labelledby="{uid}-agg-heading">
		<h4 id="{uid}-agg-heading">Aggregations</h4>

		<div class="flex flex-wrap gap-2 mb-4" role="group" aria-label="Add aggregation form">
			<div class="flex-[2] min-w-[160px]">
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
				class="flex-1 min-w-[120px]"
				bind:value={newAggregation.function}
			>
				{#each aggregationFunctions as func (func)}
					<option value={func}>{func}</option>
				{/each}
			</select>

			<input
				id="{uid}-agg-alias"
				type="text"
				class="flex-[2] min-w-[160px]"
				bind:value={newAggregation.alias}
				placeholder="Alias (optional)"
			/>

			<button
				id="{uid}-agg-add"
				data-testid="agg-add-button"
				type="button"
				class="add-btn px-4 py-2 border-none rounded-sm cursor-pointer"
				style="background-color: var(--accent-primary); color: var(--bg-primary);"
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
				class="flex flex-col gap-2"
				role="list"
				aria-label="Configured aggregations"
			>
				{#each safeAggregations as agg, i (i)}
					<div
						class="flex justify-between items-center p-3 rounded-sm"
						style="background-color: var(--panel-bg); border: 1px solid var(--panel-border);"
						role="listitem"
					>
						<span class="text-sm" style="font-family: var(--font-mono); color: var(--fg-primary);">
							{agg.function}({agg.column}) as {agg.alias}
						</span>
						<button
							id={`agg-btn-remove-${i}`}
							data-testid={`agg-remove-button-${i}`}
							type="button"
							class="remove-btn px-3 py-1 text-sm rounded-sm cursor-pointer"
							style="background-color: var(--error-bg); color: var(--error-fg); border: 1px solid var(--error-border);"
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
	.add-btn:disabled {
		background-color: var(--bg-muted) !important;
		cursor: not-allowed;
		color: var(--fg-muted) !important;
		border: 1px solid var(--border-secondary);
	}
	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
