<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface Props {
		schema: Schema;
		config?: { index?: string[]; on?: string[]; variable_name?: string; value_name?: string };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	let index = $state(config.index ?? []);
	let on = $state(config.on ?? []);
	let variableName = $state(config.variable_name ?? 'variable');
	let valueName = $state(config.value_name ?? 'value');

	$effect(() => {
		config = {
			...(index.length > 0 ? { index } : {}),
			...(on.length > 0 ? { on } : {}),
			...(variableName !== 'variable' ? { variable_name: variableName } : {}),
			...(valueName !== 'value' ? { value_name: valueName } : {}),
		};
	});

	let availableColumns = $derived(
		schema.columns.filter((col) => !index.includes(col.name) && !on.includes(col.name))
	);
</script>

<div class="unpivot-config">
	<h3>Unpivot Configuration</h3>
	<p class="description">Transform wide data to long format (melt operation).</p>

	<div class="form-group">
		<label for="index">Index columns (identifiers)</label>
		<select id="index" multiple bind:value={index}>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name}</option>
			{/each}
		</select>
		<span class="hint">Hold Ctrl/Cmd to select multiple</span>
	</div>

	<div class="form-group">
		<label for="on">Columns to unpivot</label>
		<select id="on" multiple bind:value={on}>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name}</option>
			{/each}
		</select>
		<span class="hint">Hold Ctrl/Cmd to select multiple</span>
	</div>

	<div class="form-group">
		<label for="variableName">Variable column name</label>
		<input id="variableName" type="text" bind:value={variableName} placeholder="variable" />
	</div>

	<div class="form-group">
		<label for="valueName">Value column name</label>
		<input id="valueName" type="text" bind:value={valueName} placeholder="value" />
	</div>
</div>

<style>
	.unpivot-config {
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 0.25rem;
	}

	.description {
		color: var(--fg-secondary);
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

	select[multiple] {
		height: 80px;
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	input[type='text'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	.hint {
		font-size: 0.75rem;
		color: var(--fg-muted);
	}
</style>
