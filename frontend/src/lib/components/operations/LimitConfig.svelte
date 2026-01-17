<script lang="ts">
	interface Props {
		config?: { n?: number };
	}

	let { config = $bindable({ n: 10 }) }: Props = $props();

	let n = $state(config.n ?? 10);

	$effect(() => {
		config = { n };
	});
</script>

<div class="limit-config">
	<h3>Limit Configuration</h3>

	<div class="form-group">
		<label for="n">Number of rows to keep</label>
		<input id="n" type="number" bind:value={n} min="1" placeholder="e.g., 10" />
	</div>
</div>

<style>
	.limit-config {
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

	.form-group {
		margin-bottom: 0;
	}

	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}
</style>
