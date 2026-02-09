<script lang="ts">
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { FileType } from '$lib/utils/fileTypes';

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

	// Map format string to FileType for badge display
	let selectedFileType = $derived.by((): FileType | 'duckdb' => {
		const format = config.format ?? 'csv';
		// Map formats to file types - duckdb is a source type, not a file type
		if (format === 'csv') return 'csv';
		if (format === 'parquet') return 'parquet';
		if (format === 'json') return 'json';
		if (format === 'ndjson') return 'ndjson';
		return 'duckdb' as const;
	});

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
	<div class="form-group mb-4">
		<label for="export-input-filename">Filename</label>
		<input
			id="export-input-filename"
			data-testid="export-filename-input"
			type="text"
			bind:value={config.filename}
			placeholder="e.g., my_data"
			aria-describedby="export-filename-hint"
		/>
		<span id="export-filename-hint" class="hint mt-1 block text-xs text-fg-muted"
			>Extension will be added automatically</span
		>
	</div>

	<div class="form-group mb-4">
		<label for="export-select-format" class="flex items-center gap-2">
			Format
			{#if selectedFileType === 'duckdb'}
				<FileTypeBadge sourceType="duckdb" size="sm" />
			{:else}
				<FileTypeBadge fileType={selectedFileType} size="sm" />
			{/if}
		</label>
		<select id="export-select-format" data-testid="export-format-select" bind:value={config.format}>
			{#each formats as fmt (fmt.value)}
				<option value={fmt.value}>{fmt.label}</option>
			{/each}
		</select>
	</div>

	{#if showDuckDBOptions}
		<div class="form-group mb-4">
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
			<span id="export-tablename-hint" class="hint mt-1 block text-xs text-fg-muted"
				>Name of the table in the DuckDB database</span
			>
		</div>
	{/if}

	<div class="form-group mb-0">
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
		<span
			id="export-destination-hint"
			class="hint mt-1 block text-xs text-fg-muted"
			aria-live="polite"
		>
			{#if config.destination === 'download'}
				File will be downloaded to your browser
			{:else}
				File will be saved on the server
			{/if}
		</span>
	</div>
</div>
