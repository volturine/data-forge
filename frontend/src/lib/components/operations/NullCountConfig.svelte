<script lang="ts">
	interface Props {
		config?: Record<string, never>;
	}

	let { config = $bindable({} as Record<string, never>) }: Props = $props();
	void config;
</script>

<div class="config-panel">
	<h3 class="mb-2">Null Count</h3>
	<p class="description mb-2">Count null values for each column in the dataset.</p>
	<p class="info-box m-0">
		This operation will return a single row with the count of null values for each column.
	</p>
</div>
