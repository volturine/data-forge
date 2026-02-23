<script lang="ts">
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { FileType } from '$lib/utils/fileTypes';

	interface Props {
		config?: {
			format?: string;
			filename?: string;
			options?: Record<string, unknown>;
		};
	}

	let {
		config = $bindable({
			format: 'csv',
			filename: 'export',
			options: {}
		})
	}: Props = $props();

	const showDuckDBOptions = $derived(config.format === 'duckdb');
	const showFormatOptions = $derived(true);

	// Map format string to FileType for badge display
	const selectedFileType = $derived.by((): FileType | 'duckdb' => {
		const format = config.format ?? 'csv';
		if (format === 'csv') return 'csv';
		if (format === 'parquet') return 'parquet';
		if (format === 'json') return 'json';
		if (format === 'ndjson') return 'ndjson';
		return 'duckdb' as const;
	});

	const formats = [
		{ value: 'csv', label: 'CSV (.csv)' },
		{ value: 'parquet', label: 'Parquet (.parquet)' },
		{ value: 'json', label: 'JSON (.json)' },
		{ value: 'ndjson', label: 'NDJSON (.ndjson)' },
		{ value: 'duckdb', label: 'DuckDB (.duckdb)' }
	];

	const formatOptions = $derived.by(() => formats);
</script>

<div class="config-panel" role="region" aria-label="Export configuration">
	<div class="form-group mb-5">
		<div class="flex items-center gap-2">
			Destination
			<span
				class="border border-tertiary bg-tertiary px-2 py-1 text-[10px] uppercase text-fg-muted"
			>
				Browser download
			</span>
		</div>
		<span class="hint mt-1 block text-xs text-fg-muted">
			File will be downloaded to your browser
		</span>
	</div>

	<div class="form-group mb-5">
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

	{#if showFormatOptions}
		<div class="form-group mb-5">
			<label for="export-select-format" class="flex items-center gap-2">
				Format
				{#if selectedFileType === 'duckdb'}
					<FileTypeBadge sourceType="duckdb" size="sm" />
				{:else}
					<FileTypeBadge fileType={selectedFileType} size="sm" />
				{/if}
			</label>
			<select
				id="export-select-format"
				data-testid="export-format-select"
				bind:value={config.format}
			>
				{#each formatOptions as fmt (fmt.value)}
					<option value={fmt.value}>{fmt.label}</option>
				{/each}
			</select>
		</div>
	{/if}

	{#if showDuckDBOptions}
		<div class="form-group mb-0">
			<label for="export-input-tablename">Table Name</label>
			<input
				id="export-input-tablename"
				data-testid="export-tablename-input"
				type="text"
				value={config.options?.table_name ?? 'data'}
				oninput={(e) => (config.options = { ...config.options, table_name: e.currentTarget.value })}
				placeholder="e.g., my_data"
				aria-describedby="export-tablename-hint"
			/>
			<span id="export-tablename-hint" class="hint mt-1 block text-xs text-fg-muted"
				>Name of the table in the DuckDB database</span
			>
		</div>
	{/if}
</div>
