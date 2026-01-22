<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface Props {
		schema: Schema;
		config?: { column?: string; normalize?: boolean; sort?: boolean };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	let column = $state(config.column ?? '');
	let normalize = $state(config.normalize ?? false);
	let sort = $state(config.sort ?? true);

	$effect(() => {
		config = {
			...(column ? { column } : {}),
			...(normalize ? { normalize } : {}),
			...(sort !== true ? { sort } : {})
		};
	});
</script>

<div class="value-counts-config">
	<h3>Value Counts</h3>

	<div class="form-group">
		<label for="column">Column to count</label>
		<select id="column" bind:value={column}>
			<option value="">Select column...</option>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name} ({col.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input id="normalize" type="checkbox" bind:checked={normalize} />
			<span>Normalize (show proportions instead of counts)</span>
		</label>
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input id="sort" type="checkbox" bind:checked={sort} />
			<span>Sort by count</span>
		</label>
	</div>
</div>

<style>
	.value-counts-config {
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

	.form-group {
		margin-bottom: 1rem;
	}

	.form-group:last-child {
		margin-bottom: 0;
	}

	label {
		display: block;
		margin-bottom: 0.25rem;
		color: var(--fg-secondary);
	}

	select {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		color: var(--fg-secondary);
	}
</style>
