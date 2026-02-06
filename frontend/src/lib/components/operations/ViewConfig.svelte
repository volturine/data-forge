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
		<label for="row-limit" class="flex flex-col gap-2">
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
		<p class="mt-2 mb-0 text-sm font-normal" style="color: var(--fg-tertiary);">
			Number of rows to display (10-1000)
		</p>
	</div>
</div>
