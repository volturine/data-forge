<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { getDatasource, updateDatasource, getDatasourceSchema } from '$lib/api/datasource';
	import { ArrowLeft, Save, Loader, CircleAlert } from 'lucide-svelte';
	import type {
		DataSource,
		SchemaInfo,
		ColumnSchema,
		FileDataSourceConfig,
		IcebergDataSourceConfig
	} from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';
	import { formatDateDisplay } from '$lib/utils/datetime';
	import { resolveColumnType } from '$lib/utils/columnTypes';

	const queryClient = useQueryClient();
	const datasourceId = $derived(page.params.id);

	const datasourceQuery = createQuery(() => ({
		queryKey: ['datasource', datasourceId],
		queryFn: async () => {
			if (!datasourceId) throw new Error('No datasource ID provided');
			const result = await getDatasource(datasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasourceId
	}));

	const schemaQuery = createQuery(() => ({
		queryKey: ['datasource-schema', datasourceId],
		queryFn: async () => {
			if (!datasourceId) throw new Error('No datasource ID provided');
			const result = await getDatasourceSchema(datasourceId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasourceId && !!datasourceQuery.data
	}));

	const updateMutation = createMutation(() => ({
		mutationFn: async (update: { name: string; config: Record<string, unknown> }) => {
			if (!datasourceId) throw new Error('No datasource ID provided');
			const result = await updateDatasource(datasourceId, update);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['datasource', datasourceId] });
			queryClient.invalidateQueries({ queryKey: ['datasource-schema', datasourceId] });
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
		}
	}));

	let name = $state('');
	let columns = $state<ColumnSchema[]>([]);
	let hasChanges = $state(false);
	let schemaModified = $state(false);
	let activeTab = $state<'general' | 'schema' | 'csv' | 'excel'>('general');
	let initialized = $state(false);
	let parsingOptionsTimer: ReturnType<typeof setTimeout> | null = null;
	let isSavingParsing = $state(false);
	function formatDate(dateString: string): string {
		return formatDateDisplay(dateString);
	}

	$effect(() => {
		if (!datasourceId) return;
		initialized = false;
		hasChanges = false;
		schemaModified = false;
		columns = [];
	});

	$effect(() => {
		const data = datasourceQuery.data;
		if (!data) return;
		if (initialized) return;
		name = data.name;
		const config = data.config as unknown as FileDataSourceConfig;
		if (isCsv(data)) {
			const opts = config.csv_options;
			csvConfig = {
				delimiter: opts?.delimiter ?? ',',
				quote_char: opts?.quote_char ?? '"',
				has_header: opts?.has_header ?? true,
				skip_rows: opts?.skip_rows ?? 0,
				encoding: opts?.encoding ?? 'utf8'
			};
		}
		if (isExcel(data)) {
			excelConfig = {
				sheet_name: config.sheet_name ?? '',
				table_name: config.table_name ?? '',
				named_range: config.named_range ?? '',
				start_row: config.start_row ?? 0,
				start_col: config.start_col ?? 0,
				end_col: config.end_col ?? 0,
				has_header: config.has_header ?? true
			};
		}
		initialized = true;
	});

	$effect(() => {
		if (!schemaQuery.data) return;
		setSchema(schemaQuery.data);
	});

	// CSV-specific state
	let csvConfig = $state<{
		delimiter: string;
		quote_char: string;
		has_header: boolean;
		skip_rows: number;
		encoding: string;
	}>({
		delimiter: ',',
		quote_char: '"',
		has_header: true,
		skip_rows: 0,
		encoding: 'utf8'
	});

	// Excel-specific state
	let excelConfig = $state<{
		sheet_name: string;
		table_name: string;
		named_range: string;
		start_row: number;
		start_col: number;
		end_col: number;
		has_header: boolean;
	}>({
		sheet_name: '',
		table_name: '',
		named_range: '',
		start_row: 0,
		start_col: 0,
		end_col: 0,
		has_header: true
	});

	function setSchema(value: SchemaInfo | null | undefined) {
		if (!value) return;
		if (schemaModified) return;
		if (!value.columns?.length) {
			columns = [];
			return;
		}
		// Normalize dtypes to handle parameterized types like "Datetime(time_unit='us', time_zone=None)"
		columns = value.columns.map((col) => ({
			...col,
			dtype: resolveColumnType(col.dtype)
		}));
	}

	function isCsv(datasource: DataSource): boolean {
		if (datasource.source_type !== 'file') return false;
		const config = datasource.config as unknown as FileDataSourceConfig;
		return config.file_type === 'csv';
	}

	function isExcel(datasource: DataSource): boolean {
		if (datasource.source_type !== 'file') return false;
		const config = datasource.config as unknown as FileDataSourceConfig;
		return config.file_type === 'xlsx';
	}

	function isFile(datasource: DataSource): boolean {
		return datasource.source_type === 'file';
	}

	function isIceberg(datasource: DataSource): boolean {
		return datasource.source_type === 'iceberg';
	}

	function handleNameChange(newName: string) {
		name = newName;
		hasChanges = true;
	}

	function handleColumnNameChange(index: number, newName: string) {
		columns = columns.map((col, i) => (i === index ? { ...col, name: newName } : col));
		hasChanges = true;
		schemaModified = true;
	}

	function handleColumnTypeChange(index: number, newType: string) {
		columns = columns.map((col, i) => (i === index ? { ...col, dtype: newType } : col));
		hasChanges = true;
		schemaModified = true;
	}

	async function handleCsvConfigChange<K extends keyof typeof csvConfig>(
		key: K,
		value: (typeof csvConfig)[K]
	) {
		csvConfig = { ...csvConfig, [key]: value };
		hasChanges = true;

		// Clear existing timer
		if (parsingOptionsTimer) {
			clearTimeout(parsingOptionsTimer);
			parsingOptionsTimer = null;
		}

		// Auto-save when parsing options change (affects schema)
		if (['delimiter', 'skip_rows', 'has_header'].includes(key as string)) {
			// Immediate save for delimiter and has_header (select/checkbox)
			// Debounced save for skip_rows (numeric input)
			if (key === 'skip_rows') {
				parsingOptionsTimer = setTimeout(async () => {
					await saveParsingOptions();
				}, 500);
			} else {
				await saveParsingOptions();
			}
		}
	}

	async function handleExcelConfigChange<K extends keyof typeof excelConfig>(
		key: K,
		value: (typeof excelConfig)[K]
	) {
		excelConfig = { ...excelConfig, [key]: value };
		hasChanges = true;

		// Clear existing timer
		if (parsingOptionsTimer) {
			clearTimeout(parsingOptionsTimer);
			parsingOptionsTimer = null;
		}

		// Auto-save when parsing options change (affects schema)
		if (
			[
				'sheet_name',
				'start_row',
				'start_col',
				'end_col',
				'table_name',
				'named_range',
				'has_header'
			].includes(key as string)
		) {
			// Immediate save for sheet_name, table_name, named_range, has_header (text/checkbox)
			// Debounced save for numeric inputs
			if (['start_row', 'start_col', 'end_col'].includes(key as string)) {
				parsingOptionsTimer = setTimeout(async () => {
					await saveParsingOptions();
				}, 500);
			} else {
				await saveParsingOptions();
			}
		}
	}

	async function saveParsingOptions() {
		if (!datasourceQuery.data) return;

		isSavingParsing = true;
		const update: { name: string; config: Record<string, unknown> } = { name, config: {} };

		if (isCsv(datasourceQuery.data)) {
			update.config = {
				...datasourceQuery.data.config,
				csv_options: {
					delimiter: csvConfig.delimiter,
					quote_char: csvConfig.quote_char,
					has_header: csvConfig.has_header,
					skip_rows: csvConfig.skip_rows,
					encoding: csvConfig.encoding
				}
			};
		} else if (isExcel(datasourceQuery.data)) {
			update.config = {
				...datasourceQuery.data.config,
				sheet_name: excelConfig.sheet_name || null,
				table_name: excelConfig.table_name || null,
				named_range: excelConfig.named_range || null,
				start_row: excelConfig.start_row,
				start_col: excelConfig.start_col,
				end_col: excelConfig.end_col,
				has_header: excelConfig.has_header
			};
		}

		// Save without column_schema - just parsing options
		const save = updateMutation.mutateAsync(update);
		save.finally(() => {
			isSavingParsing = false;
		});
		const saved = await save.then(
			() => true,
			() => false
		);
		if (!saved) return;

		queryClient.removeQueries({ queryKey: ['datasource-schema', datasourceId] });
		columns = [];
		hasChanges = false;
		schemaModified = false;

		if (!datasourceId) return;
		const result = await getDatasourceSchema(datasourceId);
		if (result.isOk()) {
			setSchema(result.value);
		}
	}

	function cellLabel(col: number): string {
		let idx = col + 1;
		let label = '';
		while (idx > 0) {
			const rem = (idx - 1) % 26;
			label = String.fromCharCode(65 + rem) + label;
			idx = Math.floor((idx - 1) / 26);
		}
		return label;
	}

	async function handleSave() {
		if (!datasourceQuery.data) return;

		const update: { name: string; config: Record<string, unknown> } = { name, config: {} };

		if (isCsv(datasourceQuery.data)) {
			update.config = {
				...datasourceQuery.data.config,
				csv_options: {
					delimiter: csvConfig.delimiter,
					quote_char: csvConfig.quote_char,
					has_header: csvConfig.has_header,
					skip_rows: csvConfig.skip_rows,
					encoding: csvConfig.encoding
				}
			};
		} else if (isExcel(datasourceQuery.data)) {
			update.config = {
				...datasourceQuery.data.config,
				sheet_name: excelConfig.sheet_name || null,
				table_name: excelConfig.table_name || null,
				named_range: excelConfig.named_range || null,
				start_row: excelConfig.start_row,
				start_col: excelConfig.start_col,
				end_col: excelConfig.end_col,
				has_header: excelConfig.has_header
			};
		} else if (isFile(datasourceQuery.data)) {
			update.config = { ...datasourceQuery.data.config };
		}

		// Only include column_schema if schema was actually modified
		if (schemaModified && columns.length > 0) {
			update.config.column_schema = columns;
		}

		updateMutation.mutate(update);
		hasChanges = false;
		schemaModified = false;
		initialized = false;
	}

	function handleBack() {
		goto(resolve('/datasources'), { invalidateAll: true });
	}

	async function handleRefreshRows() {
		if (!datasourceId) return;
		await getDatasourceSchema(datasourceId, { refresh: true });
		await schemaQuery.refetch();
	}
</script>

<div class="container">
	<header class="page-header">
		<div class="header-left">
			<button class="btn-back" onclick={handleBack}>
				<ArrowLeft size={20} />
			</button>
			<div class="header-text">
				<h1>Edit Data Source</h1>
				{#if datasourceQuery.data}
					<p class="subtitle">{datasourceQuery.data.name}</p>
				{/if}
			</div>
		</div>
		<button
			class="btn-primary"
			onclick={handleSave}
			disabled={!hasChanges || updateMutation.isPending}
		>
			{#if updateMutation.isPending}
				<Loader size={16} class="spin" />
				Saving...
			{:else}
				<Save size={16} />
				Save Changes
			{/if}
		</button>
	</header>

	{#if datasourceQuery.isLoading}
		<div class="loading-state">
			<Loader size={32} class="spin" />
			<p>Loading data source...</p>
		</div>
	{:else if datasourceQuery.isError}
		<div class="error-box">
			<CircleAlert size={20} />
			<div>
				<p class="error-title">Error loading data source</p>
				<p class="error-message">
					{datasourceQuery.error instanceof Error ? datasourceQuery.error.message : 'Unknown error'}
				</p>
			</div>
		</div>
	{:else if datasourceQuery.data}
		{@const datasource = datasourceQuery.data}
		{@const csv = isCsv(datasource)}
		{@const excel = isExcel(datasource)}

		<div class="tabs">
			<button
				class="tab"
				class:active={activeTab === 'general'}
				onclick={() => (activeTab = 'general')}
			>
				General
			</button>
			<button
				class="tab"
				class:active={activeTab === 'schema'}
				onclick={() => (activeTab = 'schema')}
			>
				Schema
			</button>
			{#if csv}
				<button class="tab" class:active={activeTab === 'csv'} onclick={() => (activeTab = 'csv')}>
					CSV Options
				</button>
			{/if}
			{#if excel}
				<button
					class="tab"
					class:active={activeTab === 'excel'}
					onclick={() => (activeTab = 'excel')}
				>
					Excel Options
				</button>
			{/if}
		</div>

		{#if updateMutation.isError}
			<div class="error-box">
				<CircleAlert size={20} />
				<div>
					<p class="error-title">Error saving changes</p>
					<p class="error-message">
						{updateMutation.error instanceof Error ? updateMutation.error.message : 'Unknown error'}
					</p>
				</div>
			</div>
		{/if}

		{#if updateMutation.isSuccess}
			<div class="success-box">
				<p>Changes saved successfully!</p>
			</div>
		{/if}

		<div class="content">
			{#if activeTab === 'general'}
				<div class="form">
					<div class="form-group">
						<label for="datasource-name">Name</label>
						<input
							id="datasource-name"
							type="text"
							value={name}
							oninput={(e) => handleNameChange(e.currentTarget.value)}
							placeholder="Data source name"
						/>
					</div>

					<div class="info-section">
						<h3>Source Information</h3>
						<div class="info-grid">
							<div class="info-item">
								<span class="info-label">Type</span>
								<span class="info-value">{datasource.source_type}</span>
							</div>
							{#if isFile(datasource)}
								{@const config = datasource.config as unknown as FileDataSourceConfig}
								<div class="info-item">
									<span class="info-label">File Type</span>
									<FileTypeBadge path={config.file_path} size="sm" />
								</div>
							{/if}
							{#if isIceberg(datasource)}
								{@const config = datasource.config as unknown as IcebergDataSourceConfig}
								<div class="info-item">
									<span class="info-label">Metadata Path</span>
									<span class="info-value path-value">{config.metadata_path}</span>
								</div>
							{/if}
							<div class="info-item">
								<span class="info-label">Created</span>
								<span class="info-value">{formatDate(datasource.created_at)}</span>
							</div>
							{#if schemaQuery.data}
								<div class="info-item">
									<span class="info-label">Rows</span>
									<span class="info-value">
										{schemaQuery.data.row_count?.toLocaleString() ?? 'Unknown'}
									</span>
									<button
										class="btn-secondary btn-inline"
										onclick={handleRefreshRows}
										disabled={schemaQuery.isFetching}
									>
										{schemaQuery.isFetching ? 'Refreshing...' : 'Refresh'}
									</button>
								</div>
								<div class="info-item">
									<span class="info-label">Columns</span>
									<span class="info-value">{schemaQuery.data.columns.length}</span>
								</div>
							{/if}
						</div>
					</div>
				</div>
			{:else if activeTab === 'schema'}
				<div class="schema-section">
					<div class="section-header">
						<h3>Column Schema</h3>
						<p class="hint">
							Adjust column names and types. Changes will trigger re-processing of the file.
						</p>
					</div>

					{#if isSavingParsing}
						<div class="loading-state">
							<Loader size={24} class="spin" />
							<p>Refreshing schema...</p>
						</div>
					{:else if schemaQuery.isLoading}
						<div class="loading-state">
							<Loader size={24} class="spin" />
							<p>Loading schema...</p>
						</div>
					{:else if schemaQuery.isError}
						<div class="error-box">
							<CircleAlert size={20} />
							<p>Error loading schema</p>
						</div>
					{:else if columns.length > 0}
						<div class="schema-table">
							<div class="table-header">
								<span class="col-index">#</span>
								<span class="col-name">Column Name</span>
								<span class="col-type">Type</span>
								<span class="col-sample">Sample Value</span>
							</div>
							{#each columns as column, index (index)}
								<div class="table-row">
									<span class="col-index">{index + 1}</span>
									<input
										type="text"
										class="col-name-input"
										value={column.name}
										oninput={(e) => handleColumnNameChange(index, e.currentTarget.value)}
									/>
								<ColumnTypeDropdown
									value={column.dtype}
									onChange={(val) => handleColumnTypeChange(index, val)}
									placeholder="Select type..."
								/>
									<span class="col-sample" title={column.sample_value ?? ''}>
										{column.sample_value ?? '—'}
									</span>
								</div>
							{/each}
						</div>
					{:else}
						<div class="empty-state">
							<p>No schema information available.</p>
						</div>
					{/if}
				</div>
			{:else if activeTab === 'csv' && csv}
				<div class="form">
					<h3>CSV Configuration</h3>

					<div class="form-row">
						<div class="form-group">
							<label for="csv-delimiter">Delimiter</label>
							<select
								id="csv-delimiter"
								value={csvConfig.delimiter}
								onchange={(e) => handleCsvConfigChange('delimiter', e.currentTarget.value)}
							>
								<option value=",">Comma (,)</option>
								<option value=";">Semicolon (;)</option>
								<option value="\t">Tab</option>
								<option value="|">Pipe (|)</option>
								<option value=" ">Space</option>
							</select>
						</div>

						<div class="form-group">
							<label for="csv-quote">Quote Character</label>
							<select
								id="csv-quote"
								value={csvConfig.quote_char}
								onchange={(e) => handleCsvConfigChange('quote_char', e.currentTarget.value)}
							>
								<option value="&quot;">Double Quote (")</option>
								<option value="'">Single Quote (')</option>
								<option value="">None</option>
							</select>
						</div>
					</div>

					<div class="form-row">
						<div class="form-group">
							<label for="csv-encoding">Encoding</label>
							<select
								id="csv-encoding"
								value={csvConfig.encoding}
								onchange={(e) => handleCsvConfigChange('encoding', e.currentTarget.value)}
							>
								<option value="utf8">UTF-8</option>
								<option value="utf8-lossy">UTF-8 (lossy)</option>
								<option value="latin1">Latin-1 (ISO-8859-1)</option>
								<option value="ascii">ASCII</option>
							</select>
						</div>

						<div class="form-group">
							<label for="csv-skip-rows">Skip Rows</label>
							<input
								id="csv-skip-rows"
								type="number"
								min="0"
								value={csvConfig.skip_rows}
								oninput={(e) =>
									handleCsvConfigChange('skip_rows', parseInt(e.currentTarget.value) || 0)}
							/>
							<span class="hint">Number of rows to skip at the start</span>
						</div>
					</div>

					<div class="form-group checkbox-group">
						<input
							id="csv-header"
							type="checkbox"
							checked={csvConfig.has_header}
							onchange={(e) => handleCsvConfigChange('has_header', e.currentTarget.checked)}
						/>
						<label for="csv-header">First row is header</label>
					</div>
				</div>
			{:else if activeTab === 'excel' && excel}
				<div class="form">
					<h3>Excel Configuration</h3>

					<div class="form-row">
						<div class="form-group">
							<label for="excel-sheet">Sheet Name</label>
							<input
								id="excel-sheet"
								type="text"
								value={excelConfig.sheet_name}
								oninput={(e) => handleExcelConfigChange('sheet_name', e.currentTarget.value)}
								placeholder="Sheet1"
							/>
						</div>

						<div class="form-group">
							<label for="excel-table">Table Name</label>
							<input
								id="excel-table"
								type="text"
								value={excelConfig.table_name}
								oninput={(e) => handleExcelConfigChange('table_name', e.currentTarget.value)}
								placeholder="Optional"
							/>
						</div>
					</div>

					<div class="form-group">
						<label for="excel-range">Named Range</label>
						<input
							id="excel-range"
							type="text"
							value={excelConfig.named_range}
							oninput={(e) => handleExcelConfigChange('named_range', e.currentTarget.value)}
							placeholder="Optional"
						/>
					</div>

					<div class="bounds-section">
						<h4>Table Bounds</h4>
						<div class="form-row">
							<div class="form-group">
								<label for="start-row">Start Row (0-based)</label>
								<input
									id="start-row"
									type="number"
									min="0"
									value={excelConfig.start_row}
									oninput={(e) =>
										handleExcelConfigChange('start_row', parseInt(e.currentTarget.value) || 0)}
								/>
								<span class="hint">Excel row: {excelConfig.start_row + 1}</span>
							</div>

							<div class="form-group">
								<label for="start-col">Start Column</label>
								<input
									id="start-col"
									type="number"
									min="0"
									value={excelConfig.start_col}
									oninput={(e) =>
										handleExcelConfigChange('start_col', parseInt(e.currentTarget.value) || 0)}
								/>
								<span class="hint">Excel column: {cellLabel(excelConfig.start_col)}</span>
							</div>

							<div class="form-group">
								<label for="end-col">End Column</label>
								<input
									id="end-col"
									type="number"
									min="0"
									value={excelConfig.end_col}
									oninput={(e) =>
										handleExcelConfigChange('end_col', parseInt(e.currentTarget.value) || 0)}
								/>
								<span class="hint">Excel column: {cellLabel(excelConfig.end_col)}</span>
							</div>
						</div>
					</div>

					<div class="form-group checkbox-group">
						<input
							id="excel-header"
							type="checkbox"
							checked={excelConfig.has_header}
							onchange={(e) => handleExcelConfigChange('has_header', e.currentTarget.checked)}
						/>
						<label for="excel-header">First row is header</label>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.container {
		max-width: 900px;
		margin: 0 auto;
		padding: var(--space-6);
		min-height: 100%;
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--space-4);
		margin-bottom: var(--space-6);
		padding-bottom: var(--space-6);
		border-bottom: 1px solid var(--border-primary);
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: var(--space-4);
	}

	.btn-back {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		padding: 0;
		background: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		color: var(--fg-secondary);
		cursor: pointer;
		transition: all var(--transition);
	}

	.btn-back:hover {
		background: var(--bg-hover);
		color: var(--fg-primary);
	}

	.header-text h1 {
		margin: 0 0 var(--space-1) 0;
		font-size: var(--text-2xl);
		font-weight: var(--font-semibold);
	}

	.subtitle {
		margin: 0;
		color: var(--fg-tertiary);
		font-size: var(--text-sm);
	}

	.btn-primary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-4);
		background: var(--primary-bg);
		color: var(--primary-fg);
		border: none;
		border-radius: var(--radius-sm);
		font-weight: var(--font-medium);
		cursor: pointer;
		transition: all var(--transition);
	}

	.btn-primary:hover:not(:disabled) {
		background: var(--primary-hover);
	}

	.btn-primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.btn-inline {
		margin-top: var(--space-1);
		align-self: flex-start;
		padding: 4px 10px;
		font-size: var(--text-xs);
	}

	.tabs {
		display: flex;
		gap: var(--space-2);
		border-bottom: 2px solid var(--border-primary);
		margin-bottom: var(--space-6);
	}

	.tab {
		padding: var(--space-3) var(--space-5);
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		cursor: pointer;
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		color: var(--fg-muted);
		margin-bottom: -2px;
		transition: all var(--transition);
	}

	.tab:hover {
		color: var(--fg-secondary);
	}

	.tab.active {
		color: var(--accent-primary);
		border-bottom-color: var(--accent-primary);
	}

	.content {
		background-color: var(--bg-primary);
		padding: var(--space-6);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-primary);
	}

	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.form-row {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: var(--space-4);
	}

	label {
		font-weight: var(--font-medium);
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}

	input[type='text'],
	input[type='number'],
	select {
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--input-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		background-color: var(--input-bg);
		transition: border-color var(--transition);
	}

	input[type='text']:focus,
	input[type='number']:focus,
	select:focus {
		outline: none;
		border-color: var(--border-focus);
		box-shadow: 0 0 0 3px var(--accent-bg);
	}

	.hint {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		margin: 0;
	}

	.checkbox-group {
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
	}

	.checkbox-group input {
		width: auto;
	}

	.checkbox-group label {
		margin: 0;
	}

	input[type='checkbox'] {
		width: 1rem;
		height: 1rem;
		cursor: pointer;
	}

	.info-section {
		margin-top: var(--space-4);
		padding-top: var(--space-4);
		border-top: 1px solid var(--border-primary);
	}

	.info-section h3 {
		margin: 0 0 var(--space-4) 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-secondary);
	}

	.info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: var(--space-4);
	}

	.info-item {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.info-label {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.info-value {
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		color: var(--fg-primary);
	}
	.path-value {
		word-break: break-all;
		font-size: var(--text-xs);
		color: var(--fg-secondary);
	}

	.schema-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.section-header h3 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-base);
		font-weight: var(--font-semibold);
	}

	.schema-table {
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.table-header,
	.table-row {
		display: grid;
		grid-template-columns: 50px 2fr 140px 1fr;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
	}

	.table-header {
		background-color: var(--bg-tertiary);
		font-size: var(--text-xs);
		font-weight: var(--font-semibold);
		color: var(--fg-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.table-row {
		border-top: 1px solid var(--border-primary);
	}

	.table-row:hover {
		background-color: var(--bg-hover);
	}

	.col-index {
		color: var(--fg-muted);
		font-size: var(--text-xs);
	}

	.col-name-input {
		width: 100%;
	}

	.col-sample {
		font-size: var(--text-sm);
		color: var(--fg-muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 200px;
	}

	.bounds-section {
		padding: var(--space-4);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-primary);
	}

	.bounds-section h4 {
		margin: 0 0 var(--space-4) 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-secondary);
	}

	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-4);
		padding: var(--space-12);
		color: var(--fg-muted);
	}

	.error-box {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		padding: var(--space-4);
		background-color: var(--error-bg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		color: var(--error-fg);
		margin-bottom: var(--space-4);
	}

	.error-box div {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.error-title {
		font-weight: var(--font-semibold);
		margin: 0;
	}

	.error-message {
		font-size: var(--text-sm);
		margin: 0;
		opacity: 0.8;
	}

	.success-box {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-4);
		background-color: var(--success-bg);
		border: 1px solid var(--success-border);
		border-radius: var(--radius-sm);
		color: var(--success-fg);
		margin-bottom: var(--space-4);
	}

	.success-box p {
		margin: 0;
		font-size: var(--text-sm);
	}

	.empty-state {
		text-align: center;
		padding: var(--space-8);
		color: var(--fg-muted);
	}

	.empty-state p {
		margin: 0;
	}

	:global(.spin) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}
</style>
