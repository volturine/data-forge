<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface Props {
		schema: Schema;
		config?: { column?: string; k?: number; descending?: boolean };
	}

	let { schema, config = $bindable({ column: '', k: 10, descending: false }) }: Props = $props();

	function setK(value: string) {
		const num = parseInt(value, 10);
		config.k = isNaN(num) ? 10 : num;
	}

	function setDescending(checked: boolean) {
		config.descending = checked;
	}
</script>

<div class="config-panel" role="region" aria-label="Top K configuration">
	<h3>Top K Configuration</h3>

	<div class="form-group">
		<label for="topk-select-column">Column to sort by</label>
		<select id="topk-select-column" data-testid="topk-column-select" bind:value={config.column}>
			<option value="">Select column...</option>
			{#each schema.columns as col (col.name)}
				<option value={col.name}>{col.name} ({col.dtype})</option>
			{/each}
		</select>
	</div>

	<div class="form-group">
		<label for="topk-input-k">Number of rows (k)</label>
		<input
			id="topk-input-k"
			data-testid="topk-k-input"
			type="number"
			value={config.k}
			oninput={(e) => setK(e.currentTarget.value)}
			min="1"
			placeholder="e.g., 10"
		/>
	</div>

	<div class="form-group">
		<label class="checkbox-label">
			<input
				id="topk-checkbox-descending"
				data-testid="topk-descending-checkbox"
				type="checkbox"
				checked={config.descending}
				onchange={(e) => setDescending(e.currentTarget.checked)}
				aria-describedby="topk-descending-help"
			/>
			<span>Descending (largest first)</span>
		</label>
		<span id="topk-descending-help" class="sr-only"
			>Sort in descending order (largest values first)</span
		>
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
