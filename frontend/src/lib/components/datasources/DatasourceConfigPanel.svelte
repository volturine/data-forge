<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { getDatasource, updateDatasource, getDatasourceSchema } from '$lib/api/datasource';
	import { listEngineRuns, type EngineRun } from '$lib/api/engine-runs';
	import {
		Save,
		Loader,
		CircleAlert,
		RefreshCw,
		Eye,
		Download,
		CircleCheck,
		CircleX
	} from 'lucide-svelte';
	import type {
		DataSource,
		SchemaInfo,
		ColumnSchema,
		FileDataSourceConfig,
		IcebergDataSourceConfig
	} from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { formatDateDisplay } from '$lib/utils/datetime';
	import { resolveColumnType } from '$lib/utils/columnTypes';

	interface Props {
		datasource: DataSource;
		onSave?: () => void;
	}

	let { datasource, onSave }: Props = $props();

	const queryClient = useQueryClient();

	const datasourceQuery = createQuery(() => ({
		queryKey: ['datasource', datasource.id],
		queryFn: async () => {
			const result = await getDatasource(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		initialData: datasource
	}));

	const schemaQuery = createQuery(() => ({
		queryKey: ['datasource-schema', datasource.id],
		queryFn: async () => {
			const result = await getDatasourceSchema(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasource.id
	}));

	const runsQuery = createQuery(() => ({
		queryKey: ['datasource-runs', datasource.id],
		queryFn: async () => {
			const result = await listEngineRuns({ datasource_id: datasource.id, limit: 50 });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasource.id
	}));

	const updateMutation = createMutation(() => ({
		mutationFn: async (update: { name: string; config: Record<string, unknown> }) => {
			const result = await updateDatasource(datasource.id, update);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['datasource', datasource.id] });
			queryClient.invalidateQueries({ queryKey: ['datasource-schema', datasource.id] });
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
			onSave?.();
		}
	}));

	let name = $state('');
	let columns = $state<ColumnSchema[]>([]);
	let hasChanges = $state(false);
	let isRefreshing = $state(false);
	let refreshError = $state<string | null>(null);
	let schemaChanged = $state(false);
	let schemaDiff = $state<{ added: string[]; removed: string[]; types: string[] } | null>(null);
	let activeTab = $state<'general' | 'schema' | 'csv' | 'excel' | 'runs'>('general');

	// Reset state when datasource changes
	$effect(() => {
		const ds = datasource;
		if (!ds) return;

		// Reset all state for new datasource
		name = ds.name;
		columns = [];
		hasChanges = false;
		isRefreshing = false;
		refreshError = null;
		schemaChanged = false;
		schemaDiff = null;
		activeTab = 'general';

		// Initialize type-specific config
		const config = ds.config as unknown as FileDataSourceConfig;
		if (isCsv(ds)) {
			const opts = config.csv_options;
			csvConfig = {
				delimiter: opts?.delimiter ?? ',',
				quote_char: opts?.quote_char ?? '"',
				has_header: opts?.has_header ?? true,
				skip_rows: opts?.skip_rows ?? 0,
				encoding: opts?.encoding ?? 'utf8'
			};
		}
		if (isExcel(ds)) {
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

	$effect(() => {
		if (!schemaQuery.data) return;
		setSchema(schemaQuery.data);
	});

	function setSchema(value: SchemaInfo | null | undefined) {
		if (!value) return;
		if (!value.columns?.length) {
			columns = [];
			return;
		}
		columns = value.columns.map((col) => ({
			...col,
			dtype: resolveColumnType(col.dtype)
		}));
	}

	function isCsv(ds: DataSource): boolean {
		if (ds.source_type !== 'file') return false;
		const config = ds.config as unknown as FileDataSourceConfig;
		return config.file_type === 'csv';
	}

	function isExcel(ds: DataSource): boolean {
		if (ds.source_type !== 'file') return false;
		const config = ds.config as unknown as FileDataSourceConfig;
		return config.file_type === 'xlsx';
	}

	function isFile(ds: DataSource): boolean {
		return ds.source_type === 'file';
	}

	function isIceberg(ds: DataSource): boolean {
		return ds.source_type === 'iceberg';
	}

	function handleNameChange(newName: string) {
		name = newName;
		hasChanges = true;
	}

	function handleCsvConfigChange<K extends keyof typeof csvConfig>(
		key: K,
		value: (typeof csvConfig)[K]
	) {
		csvConfig = { ...csvConfig, [key]: value };
		hasChanges = true;
	}

	function handleExcelConfigChange<K extends keyof typeof excelConfig>(
		key: K,
		value: (typeof excelConfig)[K]
	) {
		excelConfig = { ...excelConfig, [key]: value };
		hasChanges = true;
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

		updateMutation.mutate(update);
		hasChanges = false;
	}

	async function handleRefresh() {
		refreshError = null;
		isRefreshing = true;
		const previousColumns = new Map(columns.map((col) => [col.name, col.dtype]));

		try {
			const result = await getDatasourceSchema(datasource.id, { refresh: true });
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			const nextSchema = result.value;
			const nextColumns = nextSchema.columns.map((col) => ({
				name: col.name,
				dtype: resolveColumnType(col.dtype)
			}));
			const nextMap = new Map(nextColumns.map((col) => [col.name, col.dtype]));
			const added = nextColumns
				.filter((col) => !previousColumns.has(col.name))
				.map((col) => col.name);
			const removed = Array.from(previousColumns.keys()).filter((col) => !nextMap.has(col));
			const types = nextColumns
				.filter(
					(col) => previousColumns.has(col.name) && previousColumns.get(col.name) !== col.dtype
				)
				.map((col) => col.name);
			schemaChanged = added.length > 0 || removed.length > 0 || types.length > 0;
			schemaDiff = schemaChanged ? { added, removed, types } : null;
			setSchema(nextSchema);
			queryClient.invalidateQueries({ queryKey: ['datasource-schema', datasource.id] });
			queryClient.invalidateQueries({ queryKey: ['datasource-preview', datasource.id] });
		} catch (error) {
			refreshError = error instanceof Error ? error.message : 'Failed to refresh schema';
		} finally {
			isRefreshing = false;
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

	const ds = $derived(datasourceQuery.data ?? datasource);
	const csv = $derived(isCsv(ds));
	const excel = $derived(isExcel(ds));
	const runs = $derived(runsQuery.data ?? []);

	function formatDuration(ms: number | null): string {
		if (ms === null) return '-';
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(2)}s`;
	}

	function getDatasourceTag(run: EngineRun): 'created' | 'updated' | null {
		const result = run.result_json;
		if (!result || typeof result !== 'object') return null;
		if (result.datasource_id !== datasource.id) return null;
		const kind = run.kind as string;
		if (kind === 'export' || kind === 'datasource_create') return 'created';
		if (kind === 'datasource_update') return 'updated';
		return null;
	}
</script>

<div class="border-t border-tertiary bg-bg-secondary">
	{#if updateMutation.isError}
		<div class="error-box m-4 mb-0 flex items-start gap-3">
			<CircleAlert size={20} />
			<div class="flex flex-col gap-1">
				<p class="m-0 font-semibold">Error saving changes</p>
				<p class="m-0 text-sm opacity-80">
					{updateMutation.error instanceof Error ? updateMutation.error.message : 'Unknown error'}
				</p>
			</div>
		</div>
	{/if}

	{#if updateMutation.isSuccess}
		<div class="success-box m-4 mb-0 flex items-center gap-2 border p-3 text-sm">
			<p class="m-0">Changes saved successfully!</p>
		</div>
	{/if}

	<div class="flex gap-0 border-b border-tertiary px-4 pt-3">
		<button
			class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'general'}
			onclick={() => (activeTab = 'general')}
		>
			General
		</button>
		<button
			class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'schema'}
			onclick={() => (activeTab = 'schema')}
		>
			Schema
		</button>
		{#if csv}
			<button
				class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
				class:active={activeTab === 'csv'}
				onclick={() => (activeTab = 'csv')}
			>
				CSV
			</button>
		{/if}
		{#if excel}
			<button
				class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
				class:active={activeTab === 'excel'}
				onclick={() => (activeTab = 'excel')}
			>
				Excel
			</button>
		{/if}
		<button
			class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'runs'}
			onclick={() => (activeTab = 'runs')}
		>
			Runs
			{#if runs.length > 0}
				<span class="ml-1 text-fg-tertiary">({runs.length})</span>
			{/if}
		</button>
	</div>

	<div class="p-4">
		{#if activeTab === 'general'}
			<div class="flex flex-col gap-4">
				<div class="flex flex-col gap-2">
					<label for="datasource-name-{datasource.id}" class="text-xs font-medium text-fg-secondary"
						>Name</label
					>
					<input
						id="datasource-name-{datasource.id}"
						type="text"
						value={name}
						oninput={(e) => handleNameChange(e.currentTarget.value)}
						placeholder="Data source name"
						class="input-base border px-3 py-2 text-sm"
					/>
				</div>

				<div class="border-t border-tertiary pt-4">
					<h3 class="m-0 mb-3 text-xs font-semibold text-fg-secondary">Source Information</h3>
					<div class="space-y-3 text-xs">
						<!-- Type & Schema -->
						<div class="flex items-center gap-4">
							<div class="flex items-center gap-2">
								<span class="uppercase tracking-wide text-fg-muted">Type</span>
								{#if isFile(ds)}
									{@const config = ds.config as unknown as FileDataSourceConfig}
									<FileTypeBadge path={config.file_path} size="sm" />
								{:else}
									<FileTypeBadge
										sourceType={ds.source_type as 'database' | 'api' | 'iceberg' | 'duckdb'}
										size="sm"
									/>
								{/if}
							</div>
						</div>

						<div class="flex flex-col gap-1">
							<span class="uppercase tracking-wide text-fg-muted">Datasource ID</span>
							<span class="break-all text-fg-secondary font-mono">{ds.id}</span>
						</div>

						<!-- File Path for file datasources -->
						{#if isFile(ds)}
							{@const config = ds.config as unknown as FileDataSourceConfig}
							<div class="flex flex-col gap-1">
								<span class="uppercase tracking-wide text-fg-muted">Location</span>
								<span class="break-all text-fg-secondary font-mono">{config.file_path}</span>
							</div>
						{/if}

						{#if ds.source_type === 'database'}
							{@const config = ds.config as unknown as { connection_string?: string }}
							{#if config.connection_string}
								<div class="flex flex-col gap-1">
									<span class="uppercase tracking-wide text-fg-muted">Location</span>
									<span class="break-all text-fg-secondary font-mono"
										>{config.connection_string}</span
									>
								</div>
							{/if}
						{/if}

						{#if ds.source_type === 'api'}
							{@const config = ds.config as unknown as { url?: string }}
							{#if config.url}
								<div class="flex flex-col gap-1">
									<span class="uppercase tracking-wide text-fg-muted">Location</span>
									<span class="break-all text-fg-secondary font-mono">{config.url}</span>
								</div>
							{/if}
						{/if}

						{#if ds.source_type === 'duckdb'}
							{@const config = ds.config as unknown as { db_path?: string | null }}
							<div class="flex flex-col gap-1">
								<span class="uppercase tracking-wide text-fg-muted">Location</span>
								<span class="break-all text-fg-secondary font-mono"
									>{config.db_path ?? 'In-memory'}</span
								>
							</div>
						{/if}

						<!-- Metadata Path for Iceberg -->
						{#if isIceberg(ds)}
							{@const config = ds.config as unknown as IcebergDataSourceConfig}
							<div class="flex flex-col gap-1">
								<span class="uppercase tracking-wide text-fg-muted">Location</span>
								<span class="break-all text-fg-secondary font-mono">{config.metadata_path}</span>
							</div>
						{/if}

						<div class="flex items-center gap-4">
							<div class="flex items-center gap-2">
								<span class="uppercase tracking-wide text-fg-muted">Created</span>
								<span class="font-medium text-fg-primary">{formatDateDisplay(ds.created_at)}</span>
							</div>
							{#if schemaQuery.data}
								<div class="flex items-center gap-2">
									<span class="uppercase tracking-wide text-fg-muted">Rows</span>
									<span class="font-medium text-fg-primary"
										>{schemaQuery.data.row_count?.toLocaleString() ?? 'Unknown'}</span
									>
								</div>
								<div class="flex items-center gap-2">
									<span class="uppercase tracking-wide text-fg-muted">Columns</span>
									<span class="font-medium text-fg-primary">{schemaQuery.data.columns.length}</span>
								</div>
							{/if}
						</div>
					</div>
				</div>

				<div class="border-t border-tertiary pt-4 flex items-center justify-between gap-3">
					<button
						class="btn btn-secondary flex items-center gap-2"
						onclick={handleRefresh}
						disabled={isRefreshing || updateMutation.isPending}
					>
						{#if isRefreshing}
							<Loader size={16} class="spin" />
							Refreshing...
						{:else}
							<RefreshCw size={16} />
							Refresh
						{/if}
					</button>
					{#if hasChanges}
						<button
							class="btn btn-primary flex items-center gap-2"
							onclick={handleSave}
							disabled={updateMutation.isPending}
						>
							{#if updateMutation.isPending}
								<Loader size={16} class="spin" />
								Saving...
							{:else}
								<Save size={16} />
								Save Changes
							{/if}
						</button>
					{/if}
				</div>
			</div>
		{:else if activeTab === 'schema'}
			<div class="flex flex-col gap-3">
				{#if refreshError}
					<div class="error-box flex items-start gap-3">
						<CircleAlert size={20} />
						<div class="flex flex-col gap-1">
							<p class="m-0 font-semibold">Refresh failed</p>
							<p class="m-0 text-sm opacity-80">{refreshError}</p>
						</div>
					</div>
				{/if}
				{#if schemaChanged && schemaDiff}
					<div class="warning-box flex items-start gap-3">
						<CircleAlert size={20} />
						<div class="flex flex-col gap-1">
							<p class="m-0 font-semibold">Schema changed in source</p>
							{#if schemaDiff.added.length > 0}
								<p class="m-0 text-sm opacity-80">Added: {schemaDiff.added.join(', ')}</p>
							{/if}
							{#if schemaDiff.removed.length > 0}
								<p class="m-0 text-sm opacity-80">Removed: {schemaDiff.removed.join(', ')}</p>
							{/if}
							{#if schemaDiff.types.length > 0}
								<p class="m-0 text-sm opacity-80">Type changes: {schemaDiff.types.join(', ')}</p>
							{/if}
						</div>
					</div>
				{/if}
				{#if schemaQuery.isLoading}
					<div class="flex flex-col items-center justify-center gap-3 py-8 text-fg-muted">
						<Loader size={24} class="spin" />
						<p class="text-sm">Loading schema...</p>
					</div>
				{:else if columns.length > 0}
					<div class="border border-tertiary">
						<div
							class="grid grid-cols-[24px_1fr_140px] items-center gap-x-2 bg-tertiary px-3 py-2 text-xs font-semibold uppercase tracking-wide text-fg-muted border-b border-tertiary"
						>
							<span>#</span>
							<span>Column</span>
							<span>Type</span>
						</div>
						{#each columns as column, index (index)}
							<div
								class="grid grid-cols-[24px_1fr_140px] items-center gap-x-2 px-3 py-1.5"
								class:border-t={index > 0}
								class:border-tertiary={index > 0}
							>
								<span class="text-xs text-fg-faint">{index + 1}</span>
								<span class="text-xs text-fg-primary">{column.name}</span>
								<ColumnTypeBadge columnType={column.dtype} size="sm" showIcon={true} />
							</div>
						{/each}
					</div>
				{:else}
					<div class="py-6 text-center text-fg-muted text-sm">
						<p class="m-0">No schema information available.</p>
					</div>
				{/if}
			</div>
		{:else if activeTab === 'csv' && csv}
			<div class="flex flex-col gap-4">
				<h3 class="m-0 text-sm font-semibold">CSV Options</h3>

				<div class="grid grid-cols-2 gap-3">
					<div class="flex flex-col gap-1.5">
						<label for="csv-delimiter-{datasource.id}" class="text-xs font-medium text-fg-secondary"
							>Delimiter</label
						>
						<select
							id="csv-delimiter-{datasource.id}"
							value={csvConfig.delimiter}
							onchange={(e) => handleCsvConfigChange('delimiter', e.currentTarget.value)}
							class="input-base border px-3 py-2 text-sm"
						>
							<option value=",">Comma (,)</option>
							<option value=";">Semicolon (;)</option>
							<option value="\t">Tab</option>
							<option value="|">Pipe (|)</option>
							<option value=" ">Space</option>
						</select>
					</div>

					<div class="flex flex-col gap-1.5">
						<label for="csv-quote-{datasource.id}" class="text-xs font-medium text-fg-secondary"
							>Quote</label
						>
						<select
							id="csv-quote-{datasource.id}"
							value={csvConfig.quote_char}
							onchange={(e) => handleCsvConfigChange('quote_char', e.currentTarget.value)}
							class="input-base border px-3 py-2 text-sm"
						>
							<option value="&quot;">Double Quote (")</option>
							<option value="'">Single Quote (')</option>
							<option value="">None</option>
						</select>
					</div>

					<div class="flex flex-col gap-1.5">
						<label for="csv-encoding-{datasource.id}" class="text-xs font-medium text-fg-secondary"
							>Encoding</label
						>
						<select
							id="csv-encoding-{datasource.id}"
							value={csvConfig.encoding}
							onchange={(e) => handleCsvConfigChange('encoding', e.currentTarget.value)}
							class="input-base border px-3 py-2 text-sm"
						>
							<option value="utf8">UTF-8</option>
							<option value="utf8-lossy">UTF-8 (lossy)</option>
							<option value="latin1">Latin-1</option>
							<option value="ascii">ASCII</option>
						</select>
					</div>

					<div class="flex flex-col gap-1.5">
						<label for="csv-skip-rows-{datasource.id}" class="text-xs font-medium text-fg-secondary"
							>Skip Rows</label
						>
						<input
							id="csv-skip-rows-{datasource.id}"
							type="number"
							min="0"
							value={csvConfig.skip_rows}
							oninput={(e) =>
								handleCsvConfigChange('skip_rows', parseInt(e.currentTarget.value) || 0)}
							class="input-base border px-3 py-2 text-sm"
						/>
					</div>
				</div>

				<div class="flex items-center gap-2">
					<input
						id="csv-header-{datasource.id}"
						type="checkbox"
						checked={csvConfig.has_header}
						onchange={(e) => handleCsvConfigChange('has_header', e.currentTarget.checked)}
						class="h-4 w-4 cursor-pointer"
					/>
					<label for="csv-header-{datasource.id}" class="m-0 text-sm text-fg-secondary"
						>First row is header</label
					>
				</div>

				{#if hasChanges}
					<button
						class="btn btn-primary w-full flex items-center justify-center gap-2"
						onclick={handleSave}
						disabled={updateMutation.isPending}
					>
						{#if updateMutation.isPending}
							<Loader size={16} class="spin" />
							Saving...
						{:else}
							<Save size={16} />
							Save Changes
						{/if}
					</button>
				{/if}
			</div>
		{:else if activeTab === 'excel' && excel}
			<div class="flex flex-col gap-4">
				<h3 class="m-0 text-sm font-semibold">Excel Options</h3>

				<div class="grid grid-cols-2 gap-3">
					<div class="flex flex-col gap-1.5">
						<label for="excel-sheet-{datasource.id}" class="text-xs font-medium text-fg-secondary"
							>Sheet Name</label
						>
						<input
							id="excel-sheet-{datasource.id}"
							type="text"
							value={excelConfig.sheet_name}
							oninput={(e) => handleExcelConfigChange('sheet_name', e.currentTarget.value)}
							placeholder="Sheet1"
							class="input-base border px-3 py-2 text-sm"
						/>
					</div>

					<div class="flex flex-col gap-1.5">
						<label for="excel-table-{datasource.id}" class="text-xs font-medium text-fg-secondary"
							>Table Name</label
						>
						<input
							id="excel-table-{datasource.id}"
							type="text"
							value={excelConfig.table_name}
							oninput={(e) => handleExcelConfigChange('table_name', e.currentTarget.value)}
							placeholder="Optional"
							class="input-base border px-3 py-2 text-sm"
						/>
					</div>
				</div>

				<div class="flex flex-col gap-1.5">
					<label for="excel-range-{datasource.id}" class="text-xs font-medium text-fg-secondary"
						>Named Range</label
					>
					<input
						id="excel-range-{datasource.id}"
						type="text"
						value={excelConfig.named_range}
						oninput={(e) => handleExcelConfigChange('named_range', e.currentTarget.value)}
						placeholder="Optional"
						class="input-base border px-3 py-2 text-sm"
					/>
				</div>

				<div class="border border-tertiary bg-tertiary p-3">
					<h4 class="m-0 mb-3 text-xs font-semibold text-fg-secondary">Table Bounds</h4>
					<div class="grid grid-cols-3 gap-3">
						<div class="flex flex-col gap-1.5">
							<label
								for="excel-start-row-{datasource.id}"
								class="text-xs font-medium text-fg-secondary">Start Row</label
							>
							<input
								id="excel-start-row-{datasource.id}"
								type="number"
								min="0"
								value={excelConfig.start_row}
								oninput={(e) =>
									handleExcelConfigChange('start_row', parseInt(e.currentTarget.value) || 0)}
								class="input-base border px-3 py-2 text-sm"
							/>
							<span class="text-xs text-fg-muted">Row {excelConfig.start_row + 1}</span>
						</div>

						<div class="flex flex-col gap-1.5">
							<label
								for="excel-start-col-{datasource.id}"
								class="text-xs font-medium text-fg-secondary">Start Col</label
							>
							<input
								id="excel-start-col-{datasource.id}"
								type="number"
								min="0"
								value={excelConfig.start_col}
								oninput={(e) =>
									handleExcelConfigChange('start_col', parseInt(e.currentTarget.value) || 0)}
								class="input-base border px-3 py-2 text-sm"
							/>
							<span class="text-xs text-fg-muted">{cellLabel(excelConfig.start_col)}</span>
						</div>

						<div class="flex flex-col gap-1.5">
							<label
								for="excel-end-col-{datasource.id}"
								class="text-xs font-medium text-fg-secondary">End Col</label
							>
							<input
								id="excel-end-col-{datasource.id}"
								type="number"
								min="0"
								value={excelConfig.end_col}
								oninput={(e) =>
									handleExcelConfigChange('end_col', parseInt(e.currentTarget.value) || 0)}
								class="input-base border px-3 py-2 text-sm"
							/>
							<span class="text-xs text-fg-muted">{cellLabel(excelConfig.end_col)}</span>
						</div>
					</div>
				</div>

				<div class="flex items-center gap-2">
					<input
						id="excel-header-{datasource.id}"
						type="checkbox"
						checked={excelConfig.has_header}
						onchange={(e) => handleExcelConfigChange('has_header', e.currentTarget.checked)}
						class="h-4 w-4 cursor-pointer"
					/>
					<label for="excel-header-{datasource.id}" class="m-0 text-sm text-fg-secondary"
						>First row is header</label
					>
				</div>

				{#if hasChanges}
					<button
						class="btn btn-primary w-full flex items-center justify-center gap-2"
						onclick={handleSave}
						disabled={updateMutation.isPending}
					>
						{#if updateMutation.isPending}
							<Loader size={16} class="spin" />
							Saving...
						{:else}
							<Save size={16} />
							Save Changes
						{/if}
					</button>
				{/if}
			</div>
		{:else if activeTab === 'runs'}
			<div class="flex flex-col gap-3">
				{#if runsQuery.isLoading}
					<div class="flex flex-col items-center justify-center gap-3 py-8 text-fg-muted">
						<Loader size={24} class="spin" />
						<p class="text-sm">Loading runs...</p>
					</div>
				{:else if runs.length === 0}
					<div class="py-6 text-center text-fg-muted text-sm">
						<p class="m-0">No engine runs associated with this datasource.</p>
						<p class="m-0 mt-1 text-fg-tertiary">
							Runs will appear here when this datasource is used in analyses.
						</p>
					</div>
				{:else}
					<div class="border border-tertiary">
						<div
							class="grid grid-cols-[1fr_80px_80px_100px] items-center gap-x-2 bg-tertiary px-3 py-2 text-xs font-semibold uppercase tracking-wide text-fg-muted border-b border-tertiary"
						>
							<span>Type</span>
							<span>Status</span>
							<span>Duration</span>
							<span>Created</span>
						</div>
						{#each runs as run, index (run.id)}
							{@const dsTag = getDatasourceTag(run)}
							<div
								class="grid grid-cols-[1fr_80px_80px_100px] items-center gap-x-2 px-3 py-2"
								class:border-t={index > 0}
								class:border-tertiary={index > 0}
							>
								<div class="flex items-center gap-2 text-xs">
									{#if (run.kind as string) === 'preview'}
										<Eye size={14} class="text-accent shrink-0" />
										<span>Preview</span>
									{:else if (run.kind as string) === 'datasource_create'}
										<Save size={14} class="text-accent-primary shrink-0" />
										<span>Create</span>
									{:else if (run.kind as string) === 'datasource_update'}
										<RefreshCw size={14} class="text-warning-fg shrink-0" />
										<span>Update</span>
									{:else}
										<Download size={14} class="text-success-fg shrink-0" />
										<span>Export</span>
									{/if}
									{#if dsTag === 'created'}
										<span
											class="text-[10px] px-1.5 py-0.5 bg-accent-bg text-accent-primary rounded"
											title="This datasource was created from this export"
										>
											CREATED
										</span>
									{:else if dsTag === 'updated'}
										<span
											class="text-[10px] px-1.5 py-0.5 bg-warning-bg text-warning-fg rounded"
											title="This datasource was updated in this run"
										>
											UPDATED
										</span>
									{/if}
								</div>
								<div class="flex items-center gap-1.5 text-xs">
									{#if run.status === 'success'}
										<CircleCheck size={14} class="text-success-fg" />
										<span class="text-success-fg">Success</span>
									{:else}
										<CircleX size={14} class="text-error-fg" />
										<span class="text-error-fg">Failed</span>
									{/if}
								</div>
								<span class="text-xs font-mono text-fg-secondary">
									{formatDuration(run.duration_ms)}
								</span>
								<span class="text-xs text-fg-tertiary">
									{formatDateDisplay(run.created_at)}
								</span>
							</div>
						{/each}
					</div>
					{#if runs.length >= 50}
						<p class="text-xs text-fg-tertiary text-center">
							Showing last 50 runs.
							<a
								href="{resolve('/builds')}?datasource_id={datasource.id}"
								class="text-accent-primary hover:underline"
							>
								View all runs
							</a>
						</p>
					{/if}
				{/if}
			</div>
		{/if}
	</div>
</div>
