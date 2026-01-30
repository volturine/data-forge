<script lang="ts">
	interface Props {
		config?: {
			fraction?: number;
			seed?: number;
		};
	}

	let { config = $bindable({ fraction: 0.5, seed: 42 }) }: Props = $props();
</script>

<div class="config-panel" role="region" aria-label="Sample configuration">
	<h3>Sample Configuration</h3>

	<div class="form-group">
		<label for="sample-input-fraction">Fraction</label>
		<input
			id="sample-input-fraction"
			data-testid="sample-fraction-input"
			type="number"
			bind:value={config.fraction}
			min="0"
			max="1"
			step="0.01"
			placeholder="e.g., 0.5"
		/>
	</div>

	<div class="form-group">
		<label for="sample-input-seed">Random seed (optional)</label>
		<input
			id="sample-input-seed"
			data-testid="sample-seed-input"
			type="number"
			bind:value={config.seed}
			min="0"
			placeholder="e.g., 42"
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
</style>
