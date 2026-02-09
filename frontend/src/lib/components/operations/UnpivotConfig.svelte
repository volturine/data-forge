<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

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

	<div class="form-group mb-4">
		<div class="form-label">Index columns (identifiers)</div>
		<MultiSelectColumnDropdown
			{schema}
			value={config.index ?? []}
			onChange={(val) => (config.index = val)}
			placeholder="Select index columns..."
		/>
		<span class="mt-1 block text-xs text-fg-tertiary">Columns to use as identifiers</span>
	</div>

	<div class="form-group mb-4">
		<div class="form-label">Columns to unpivot</div>
		<MultiSelectColumnDropdown
			{schema}
			value={config.on ?? []}
			onChange={(val) => (config.on = val)}
			placeholder="Select columns to unpivot..."
		/>
		<span class="mt-1 block text-xs text-fg-tertiary">Columns that will be transformed to rows</span
		>
	</div>

	<div class="form-group mb-4">
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

	<div class="form-group mb-0">
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
