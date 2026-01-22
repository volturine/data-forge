<script lang="ts">
	interface Props {
		config?: {
			format?: string;
			filename?: string;
			destination?: string;
			options?: Record<string, unknown>;
		};
	}

	let {
		config = $bindable({
			format: 'csv',
			filename: 'export',
			destination: 'filesystem',
			options: {}
		})
	}: Props = $props();

	let format = $state(config.format ?? 'csv');
	let filename = $state(config.filename ?? 'export');
	let destination = $state(config.destination ?? 'filesystem');
	let tableName = $state((config.options?.table_name as string) ?? 'data');

	let showDuckDBOptions = $derived(format === 'duckdb');

	$effect(() => {
		config = { format, filename, destination, options: { table_name: tableName } };
	});

	const formats = [
		{ value: 'csv', label: 'CSV (.csv)' },
		{ value: 'parquet', label: 'Parquet (.parquet)' },
		{ value: 'json', label: 'JSON (.json)' },
		{ value: 'ndjson', label: 'NDJSON (.ndjson)' },
		{ value: 'duckdb', label: 'DuckDB (.duckdb)' }
	];

	const destinations = [
		{ value: 'filesystem', label: 'Server Filesystem' },
		{ value: 'download', label: 'Browser Download' }
	];
</script>

<div class="export-config" role="region" aria-label="Export configuration">
	<div class="form-group">
		<label for="export-input-filename">Filename</label>
		<input
			id="export-input-filename"
			data-testid="export-filename-input"
			type="text"
			bind:value={filename}
			placeholder="e.g., my_data"
			aria-describedby="export-filename-hint"
		/>
		<span id="export-filename-hint" class="hint">Extension will be added automatically</span>
	</div>

	<div class="form-group">
		<label for="export-select-format">Format</label>
		<select id="export-select-format" data-testid="export-format-select" bind:value={format}>
			{#each formats as fmt (fmt.value)}
				<option value={fmt.value}>{fmt.label}</option>
			{/each}
		</select>
	</div>

	{#if showDuckDBOptions}
		<div class="form-group">
			<label for="export-input-tablename">Table Name</label>
			<input
				id="export-input-tablename"
				data-testid="export-tablename-input"
				type="text"
				bind:value={tableName}
				placeholder="e.g., my_data"
				aria-describedby="export-tablename-hint"
			/>
			<span id="export-tablename-hint" class="hint">Name of the table in the DuckDB database</span>
		</div>
	{/if}

	<div class="form-group">
		<label for="export-select-destination">Destination</label>
		<select
			id="export-select-destination"
			data-testid="export-destination-select"
			bind:value={destination}
		>
			{#each destinations as dest (dest.value)}
				<option value={dest.value}>{dest.label}</option>
			{/each}
		</select>
		<span id="export-destination-hint" class="hint" aria-live="polite">
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
