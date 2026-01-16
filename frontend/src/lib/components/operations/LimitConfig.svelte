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
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	.form-group {
		margin-bottom: 0;
	}

	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}
</style>
