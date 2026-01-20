<script lang="ts">
	interface Props {
		config?: {
			format?: string;
			filename?: string;
			destination?: string;
		};
	}

	let {
		config = $bindable({ format: 'csv', filename: 'export', destination: 'filesystem' })
	}: Props = $props();

	let format = $state(config.format ?? 'csv');
	let filename = $state(config.filename ?? 'export');
	let destination = $state(config.destination ?? 'filesystem');

	$effect(() => {
		config = { format, filename, destination };
	});

	const formats = [
		{ value: 'csv', label: 'CSV (.csv)' },
		{ value: 'parquet', label: 'Parquet (.parquet)' },
		{ value: 'json', label: 'JSON (.json)' },
		{ value: 'ndjson', label: 'NDJSON (.ndjson)' }
	];

	const destinations = [
		{ value: 'filesystem', label: 'Server Filesystem' },
		{ value: 'download', label: 'Browser Download' }
	];
</script>

<div class="export-config">
	<div class="form-group">
		<label for="filename">Filename</label>
		<input id="filename" type="text" bind:value={filename} placeholder="e.g., my_data" />
		<span class="hint">Extension will be added automatically</span>
	</div>

	<div class="form-group">
		<label for="format">Format</label>
		<select id="format" bind:value={format}>
			{#each formats as fmt (fmt.value)}
				<option value={fmt.value}>{fmt.label}</option>
			{/each}
		</select>
	</div>

	<div class="form-group">
		<label for="destination">Destination</label>
		<select id="destination" bind:value={destination}>
			{#each destinations as dest (dest.value)}
				<option value={dest.value}>{dest.label}</option>
			{/each}
		</select>
		<span class="hint">
			{#if destination === 'download'}
				File will be downloaded to your browser
			{:else}
				File will be saved on the server
			{/if}
		</span>
	</div>
</div>

<style>
	.export-config {
		padding: 1rem;
	}

	.form-group {
		margin-bottom: 1rem;
	}

	.form-group:last-child {
		margin-bottom: 0;
	}

	label {
		display: block;
		margin-bottom: 0.25rem;
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}

	input[type='text'],
	select {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
		font-family: var(--font-mono);
	}

	.hint {
		display: block;
		margin-top: 0.25rem;
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
</style>
