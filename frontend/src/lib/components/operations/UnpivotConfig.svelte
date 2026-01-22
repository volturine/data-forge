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
			...(valueName !== 'value' ? { value_name: valueName } : {})
		};
	});
</script>

<div class="unpivot-config" role="region" aria-label="Unpivot configuration">
	<h3>Unpivot Configuration</h3>
	<p class="description">Transform wide data to long format (melt operation).</p>

	<div class="form-group">
		<label for="unpivot-select-index">Index columns (identifiers)</label>
		<select
			id="unpivot-select-index"
			data-testid="unpivot-index-select"
			multiple
			bind:value={index}
		>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name}</option>
			{/each}
		</select>
		<span class="hint">Hold Ctrl/Cmd to select multiple</span>
	</div>

	<div class="form-group">
		<label for="unpivot-select-on">Columns to unpivot</label>
		<select id="unpivot-select-on" data-testid="unpivot-on-select" multiple bind:value={on}>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name}</option>
			{/each}
		</select>
		<span class="hint">Hold Ctrl/Cmd to select multiple</span>
	</div>

	<div class="form-group">
		<label for="unpivot-input-variable">Variable column name</label>
		<input
			id="unpivot-input-variable"
			data-testid="unpivot-variable-input"
			type="text"
			bind:value={variableName}
			placeholder="variable"
		/>
	</div>

	<div class="form-group">
		<label for="unpivot-input-value">Value column name</label>
		<input
			id="unpivot-input-value"
			data-testid="unpivot-value-input"
			type="text"
			bind:value={valueName}
			placeholder="value"
		/>
	</div>
</div>

<style>
	.unpivot-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 0.25rem;
		color: var(--panel-header-fg);
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
		color: var(--fg-secondary);
	}

	select[multiple] {
		height: 80px;
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	input[type='text'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.hint {
		font-size: 0.75rem;
		color: var(--fg-tertiary);
	}
</style>
