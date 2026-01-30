<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface Props {
		schema: Schema;
		config?: { index?: string[]; on?: string[]; variable_name?: string; value_name?: string };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	// Helper to get config value with default
	const get = <T,>(key: keyof typeof config, defaultValue: T): T =>
		(config[key] as T) ?? defaultValue;
</script>

<div class="config-panel" role="region" aria-label="Unpivot configuration">
	<h3>Unpivot Configuration</h3>
	<p class="description">Transform wide data to long format (melt operation).</p>

	<div class="form-group">
		<label for="unpivot-select-index">Index columns (identifiers)</label>
		<select
			id="unpivot-select-index"
			data-testid="unpivot-index-select"
			multiple
			bind:value={config.index}
		>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name}</option>
			{/each}
		</select>
		<span class="hint">Hold Ctrl/Cmd to select multiple</span>
	</div>

	<div class="form-group">
		<label for="unpivot-select-on">Columns to unpivot</label>
		<select id="unpivot-select-on" data-testid="unpivot-on-select" multiple bind:value={config.on}>
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
			value={get('variable_name', 'variable')}
			oninput={(e) => (config.variable_name = e.currentTarget.value)}
			placeholder="variable"
		/>
	</div>

	<div class="form-group">
		<label for="unpivot-input-value">Value column name</label>
		<input
			id="unpivot-input-value"
			data-testid="unpivot-value-input"
			type="text"
			value={get('value_name', 'value')}
			oninput={(e) => (config.value_name = e.currentTarget.value)}
			placeholder="value"
		/>
	</div>
</div>

<style>
	.form-group {
		margin-bottom: var(--space-4);
	}
	.form-group:last-child {
		margin-bottom: 0;
	}
	select[multiple] {
		height: 80px;
	}
	.hint {
		font-size: var(--text-xs);
		color: var(--fg-tertiary);
		display: block;
		margin-top: var(--space-1);
	}
</style>
