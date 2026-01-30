<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface ViewConfigData {
		rowLimit: number;
	}

	interface Props {
		schema: Schema;
		config?: ViewConfigData;
	}

	let { schema: _schema, config = $bindable({ rowLimit: 100 }) }: Props = $props();
</script>

<div class="config-panel">
	<h3>View Configuration</h3>

	<div class="form-section">
		<label for="row-limit">
			Preview Rows
			<input
				id="row-limit"
				type="number"
				bind:value={config.rowLimit}
				min="10"
				max="1000"
				step="10"
			/>
		</label>
		<p class="help-text">Number of rows to display (10-1000)</p>
	</div>
</div>

<style>
	label {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.help-text {
		margin: var(--space-2) 0 0 0;
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
		font-weight: var(--font-normal);
	}
</style>
