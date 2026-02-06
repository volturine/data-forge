<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

	interface DeduplicateConfigData {
		subset: string[] | null;
		keep: string;
	}

	interface Props {
		schema: Schema;
		config?: DeduplicateConfigData;
	}

	let { schema, config = $bindable({ subset: null, keep: 'first' }) }: Props = $props();

	const keepStrategies = [
		{ value: 'first', label: 'Keep First' },
		{ value: 'last', label: 'Keep Last' },
		{ value: 'none', label: 'Keep None' }
	];
</script>

<div class="config-panel" role="region" aria-label="Deduplicate configuration">
	<h3>Deduplicate Configuration</h3>

	<div class="form-section" role="radiogroup" aria-labelledby="keep-strategy-heading">
		<h4 id="keep-strategy-heading">Keep Strategy</h4>
		<div class="flex flex-col gap-3">
			{#each keepStrategies as strategy (strategy.value)}
				<label
					class="strategy-option flex cursor-pointer items-start gap-3 rounded-sm border p-3 transition-all"
					style="background-color: var(--bg-primary); border-color: var(--border-primary);"
				>
					<input
						type="radio"
						name="keep-strategy"
						bind:group={config.keep}
						value={strategy.value}
						class="mr-2 cursor-pointer"
					/>
					<span>{strategy.label}</span>
				</label>
			{/each}
		</div>
	</div>

	<div class="form-section" role="group" aria-labelledby="column-subset-heading">
		<h4 id="column-subset-heading">Column Subset</h4>
		<div class="form-label">Columns to check for duplicates</div>
		<MultiSelectColumnDropdown
			{schema}
			value={config.subset ?? []}
			onChange={(val) => (config.subset = val.length > 0 ? val : null)}
			placeholder="Select columns..."
		/>

		{#if config.subset && config.subset.length > 0}
			<div class="info-box mt-2" aria-live="polite">
				Checking {config.subset.length} column{config.subset.length !== 1 ? 's' : ''} for duplicates
			</div>
		{:else}
			<div class="info-box mt-2">No columns selected - will check all columns for duplicates</div>
		{/if}
	</div>
</div>

<style>
	.strategy-option:hover {
		border-color: var(--border-focus);
		background-color: var(--bg-hover);
	}
</style>
