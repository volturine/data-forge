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

	// Ensure config has proper structure (handles empty {} from step creation)
	$effect(() => {
		if (!config || typeof config !== 'object') {
			config = { rowLimit: 100 };
		} else if (typeof config.rowLimit !== 'number' || config.rowLimit < 10) {
			config.rowLimit = 100;
		}
	});
</script>

<div class="view-config">
	<h3>View Configuration</h3>

	<div class="config-section">
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
	.view-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		color: var(--panel-header-fg);
	}

	.config-section {
		margin-bottom: 1.5rem;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		font-weight: 500;
		color: var(--fg-secondary);
	}

	input[type='number'] {
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
		font-size: 1rem;
	}

	input[type='number']:focus {
		outline: none;
		border-color: var(--input-focus-border);
		box-shadow: 0 0 0 3px var(--accent-bg);
	}

	.help-text {
		margin: 0.5rem 0 0 0;
		font-size: 0.875rem;
		color: var(--fg-tertiary);
		font-weight: normal;
	}
</style>
