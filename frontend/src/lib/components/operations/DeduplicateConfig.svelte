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
		<div class="strategy-grid">
			{#each keepStrategies as strategy (strategy.value)}
				<label class="strategy-option">
					<input
						type="radio"
						name="keep-strategy"
						bind:group={config.keep}
						value={strategy.value}
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
			<div class="info-box" aria-live="polite">
				Checking {config.subset.length} column{config.subset.length !== 1 ? 's' : ''} for duplicates
			</div>
		{:else}
			<div class="info-box">No columns selected - will check all columns for duplicates</div>
		{/if}
	</div>
</div>

<style>
	.info-box {
		margin-top: var(--space-2);
	}
	.strategy-grid {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.strategy-option {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding: var(--space-3);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition);
	}
	.strategy-option:hover {
		border-color: var(--border-focus);
		background-color: var(--bg-hover);
	}
	.strategy-option input[type='radio'] {
		margin-right: var(--space-2);
		cursor: pointer;
	}
</style>
