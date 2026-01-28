<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface Props {
		schema: Schema;
		config?: { column?: string; k?: number; descending?: boolean };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	let column = $state(config.column ?? '');
	let k = $state(config.k ?? 10);
	let descending = $state(config.descending ?? false);

	$effect(() => {
		config = {
			...(column ? { column } : {}),
			k,
			...(descending ? { descending } : {})
		};
	});
</script>

<div class="config-panel" role="region" aria-label="Top K configuration">
	<h3>Top K Configuration</h3>

	<div class="form-group">
		<label for="topk-select-column">Column to sort by</label>
		<select id="topk-select-column" data-testid="topk-column-select" bind:value={column}>
			<option value="">Select column...</option>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name} ({col.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="form-group">
		<label for="topk-input-k">Number of rows (k)</label>
		<input
			id="topk-input-k"
			data-testid="topk-k-input"
			type="number"
			bind:value={k}
			min="1"
			placeholder="e.g., 10"
		/>
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input
				id="topk-checkbox-descending"
				data-testid="topk-descending-checkbox"
				type="checkbox"
				bind:checked={descending}
				aria-describedby="topk-descending-help"
			/>
			<span>Descending (largest first)</span>
		</label>
		<span id="topk-descending-help" class="sr-only"
			>Sort in descending order (largest values first)</span
		>
	</div>
</div>

<style>
	.form-group {
		margin-bottom: var(--space-4);
	}
	.form-group:last-child {
		margin-bottom: 0;
	}
	.checkbox-label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
	}
</style>
