<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

	interface DropConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: DropConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	const safeColumns = $derived(Array.isArray(config.columns) ? config.columns : []);
</script>

<div class="config-panel" role="region" aria-label="Drop columns configuration">
	<h3>Drop Columns</h3>

	<p class="description">Select the columns you want to drop (remove) from the dataset.</p>

	<div class="form-section">
		<div class="form-label">Columns to drop</div>
		<MultiSelectColumnDropdown
			{schema}
			value={safeColumns}
			onChange={(val) => (config.columns = val)}
			placeholder="Select columns to drop..."
		/>
	</div>

	{#if safeColumns.length > 0}
		<div class="warning-box" aria-live="polite">
			<strong>⚠️ Columns to Drop ({safeColumns.length}):</strong>
			<p>These columns will be removed from the dataset.</p>
		</div>
	{:else}
		<div class="warning-box" role="alert">
			<strong>Warning:</strong> No columns selected. This operation will have no effect.
		</div>
	{/if}
</div>

<style>
	h3 {
		margin-bottom: var(--space-2);
	}
</style>
