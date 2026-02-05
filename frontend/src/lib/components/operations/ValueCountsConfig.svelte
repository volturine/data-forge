<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

	interface Props {
		schema: Schema;
		config?: { column?: string; normalize?: boolean; sort?: boolean };
	}

	let { schema, config = $bindable({}) }: Props = $props();

	// Helper to get config value with default
	const get = <T,>(key: keyof typeof config, defaultValue: T): T =>
		(config[key] as T) ?? defaultValue;
</script>

<div class="config-panel">
	<h3>Value Counts</h3>

	<div class="form-group">
		<div class="form-label">Column to count</div>
		<ColumnDropdown
			{schema}
			value={config.column ?? ''}
			onChange={(val) => (config.column = val)}
			placeholder="Select column..."
		/>
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input id="normalize" type="checkbox" bind:checked={config.normalize} />
			<span>Normalize (show proportions instead of counts)</span>
		</label>
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input
				id="sort"
				type="checkbox"
				checked={get('sort', true)}
				onchange={(e) => (config.sort = e.currentTarget.checked)}
			/>
			<span>Sort by count</span>
		</label>
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
