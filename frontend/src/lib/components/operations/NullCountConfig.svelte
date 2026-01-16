<script lang="ts">
	interface Props {
		config?: Record<string, never>;
	}

	let { config = $bindable({}) }: Props = $props();
</script>

<div class="null-count-config">
	<h3>Null Count</h3>
	<p class="description">Count null values for each column in the dataset.</p>
	<p class="info">This operation will return a single row with the count of null values for each column.</p>
</div>

<style>
	.null-count-config {
		padding: 1rem;
		border: 1px solid var(--border-primary);
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 0.5rem;
	}

	.description {
		margin-bottom: 0.5rem;
		color: var(--fg-secondary);
	}

	.info {
		font-size: 0.875rem;
		color: var(--fg-muted);
		padding: 0.5rem;
		background-color: var(--bg-tertiary);
		border-radius: 4px;
		margin: 0;
	}
</style>
