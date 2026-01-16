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
			...(descending ? { descending } : {}),
		};
	});
</script>

<div class="topk-config">
	<h3>Top K Configuration</h3>

	<div class="form-group">
		<label for="column">Column to sort by</label>
		<select id="column" bind:value={column}>
			<option value="">Select column...</option>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name} ({col.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="form-group">
		<label for="k">Number of rows (k)</label>
		<input id="k" type="number" bind:value={k} min="1" placeholder="e.g., 10" />
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input type="checkbox" bind:checked={descending} />
			<span>Descending (largest first)</span>
		</label>
	</div>
</div>

<style>
	.topk-config {
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	.form-group {
		margin-bottom: 1rem;
	}

	.form-group:last-child {
		margin-bottom: 0;
	}

	label {
		display: block;
		margin-bottom: 0.25rem;
	}

	select,
	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
	}
</style>
