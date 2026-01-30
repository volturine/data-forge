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

	let showDuckDBOptions = $derived(config.format === 'duckdb');

	function setTableName(value: string) {
		config.options = { ...config.options, table_name: value };
	}

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

<div class="config-panel" role="region" aria-label="Export configuration">
	<div class="form-group">
		<label for="export-input-filename">Filename</label>
		<input
			id="export-input-filename"
			data-testid="export-filename-input"
			type="text"
			bind:value={config.filename}
			placeholder="e.g., my_data"
			aria-describedby="export-filename-hint"
		/>
		<span id="export-filename-hint" class="hint">Extension will be added automatically</span>
	</div>

	<div class="form-group">
		<label for="export-select-format">Format</label>
		<select id="export-select-format" data-testid="export-format-select" bind:value={config.format}>
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
				value={(config.options!.table_name as string) ?? 'data'}
				oninput={(e) => setTableName(e.currentTarget.value)}
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
			bind:value={config.destination}
		>
			{#each destinations as dest (dest.value)}
				<option value={dest.value}>{dest.label}</option>
			{/each}
		</select>
		<span id="export-destination-hint" class="hint" aria-live="polite">
			{#if config.destination === 'download'}
				File will be downloaded to your browser
			{:else}
				File will be saved on the server
			{/if}
		</span>
	</div>
</div>

<style>
	.form-group {
		margin-bottom: var(--space-4);
	}

	.form-group:last-child {
		margin-bottom: 0;
	}

	.hint {
		display: block;
		margin-top: var(--space-1);
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
</style>
