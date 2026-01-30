<script lang="ts">
	import type { Schema } from '$lib/types/schema';

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
		<label for="column">Column to count</label>
		<select id="column" bind:value={config.column}>
			<option value="">Select column...</option>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name} ({col.dtype})</option>
			{/each}
		</select>
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
