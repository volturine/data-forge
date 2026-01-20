<script lang="ts">
	interface Props {
		config?: Record<string, never>;
	}

	let { config = $bindable({}) }: Props = $props();
</script>

<div class="null-count-config">
	<h3>Null Count</h3>
	<p class="description">Count null values for each column in the dataset.</p>
	<p class="info">
		This operation will return a single row with the count of null values for each column.
	</p>
</div>

<style>
	.null-count-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 0.5rem;
		color: var(--panel-header-fg);
	}

	.description {
		margin-bottom: 0.5rem;
		color: var(--fg-secondary);
	}

	.info {
		font-size: 0.875rem;
		color: var(--fg-tertiary);
		padding: 0.5rem;
		background-color: var(--panel-muted-bg);
		border: 1px solid var(--panel-muted-border);
		border-radius: var(--radius-sm);
		margin: 0;
	}
</style>
