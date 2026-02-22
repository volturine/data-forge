<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

	interface SelectConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: SelectConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	const safeColumns = $derived(Array.isArray(config.columns) ? config.columns : []);
</script>

<div class="config-panel" role="region" aria-label="Select columns configuration">
	<div class="form-section">
		<div class="form-label">Columns to keep</div>
		<MultiSelectColumnDropdown
			{schema}
			value={safeColumns}
			onChange={(val) => (config.columns = val)}
			placeholder="Select columns to keep..."
		/>
	</div>

	{#if safeColumns.length > 0}
		<div class="info-box" aria-live="polite">
			<strong>Selected {safeColumns.length} column{safeColumns.length !== 1 ? 's' : ''}</strong>
		</div>
	{/if}
</div>
