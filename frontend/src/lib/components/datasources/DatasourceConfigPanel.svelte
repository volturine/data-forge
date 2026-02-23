<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import {
		getDatasource,
		getDatasourceSchema,
		refreshDatasource,
		updateDatasource
	} from '$lib/api/datasource';
	import { listEngineRuns, type EngineRun } from '$lib/api/engine-runs';
	import { listHealthChecks, listHealthCheckResults } from '$lib/api/healthcheck';
	import {
		Save,
		Loader,
		CircleAlert,
		RefreshCw,
		Eye,
		EyeOff,
		Download,
		CircleCheck,
		CircleX,
		Upload,
		GitBranch
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
	import ExcelTableSelector from '$lib/components/common/ExcelTableSelector.svelte';
	import ColumnStatsPanel from '$lib/components/datasources/ColumnStatsPanel.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
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
		enabled: !!datasource.id && datasource.source_type !== 'analysis',
		staleTime: Infinity
	}));

	const runsQuery = createQuery(() => ({
		queryKey: ['datasource-runs', datasource.id],
		queryFn: async () => {
			const result = await listEngineRuns({ datasource_id: datasource.id, limit: 50 });
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasource.id,
		retry: false
	}));

	const healthChecksQuery = createQuery(() => ({
		queryKey: ['datasource-healthchecks-count', datasource.id],
		queryFn: async () => {
			const result = await listHealthChecks(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		enabled: !!datasource.id
	}));

	const healthResultsQuery = createQuery(() => ({
		queryKey: ['healthcheck-results', datasource.id],
		queryFn: async () => {
			const result = await listHealthCheckResults(datasource.id, 50);
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
	let activeTab = $state<'general' | 'schema' | 'csv' | 'excel' | 'runs' | 'health' | 'schedules'>(
		'general'
	);
	let statsOpen = $state(false);
	let statsColumn = $state<string | null>(null);
	let showPreviews = $state(false);

	// Subscription: $derived can't reset state on datasource changes.
	// Subscription: $derived can't sync schema into local state.
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
		statsOpen = false;
		statsColumn = null;

		// Initialize type-specific config
		const fileSource = getFileSource(ds);
		if (isCsv(ds) && fileSource) {
			const opts = fileSource.csv_options;
			csvConfig = {
				delimiter: opts?.delimiter ?? ',',
				quote_char: opts?.quote_char ?? '"',
				has_header: opts?.has_header ?? true,
				skip_rows: opts?.skip_rows ?? 0,
				encoding: opts?.encoding ?? 'utf8'
			};
		}
		if (isExcel(ds) && fileSource) {
			const excelSource = fileSource as unknown as Record<string, unknown>;
			const cellRangeValue = excelSource.cell_range;
			const cellRange = typeof cellRangeValue === 'string' ? cellRangeValue : '';
			const sheetValue = excelSource.sheet_name;
			const sheetName = typeof sheetValue === 'string' ? sheetValue : '';
			const tableValue = excelSource.table_name;
			const tableName = typeof tableValue === 'string' ? tableValue : '';
			const rangeValue = excelSource.named_range;
			const namedRange = typeof rangeValue === 'string' ? rangeValue : '';
			const endRowValue = fileSource.end_row ?? null;
			excelConfig = {
				sheet_name: sheetName,
				table_name: tableName,
				named_range: namedRange,
				cell_range: cellRange,
				start_row: fileSource.start_row ?? 0,
				start_col: fileSource.start_col ?? 0,
				end_col: fileSource.end_col ?? 0,
				end_row: endRowValue,
				has_header: fileSource.has_header ?? true
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
		cell_range: string;
		start_row: number;
		start_col: number;
		end_col: number;
		end_row: number | null;
		has_header: boolean;
	}>({
		sheet_name: '',
		table_name: '',
		named_range: '',
		cell_range: '',
		start_row: 0,
		start_col: 0,
		end_col: 0,
		end_row: null,
		has_header: true
	});

	// Network: $derived can't sync columns from async schema fetch.
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

	function getFileSource(ds: DataSource): FileDataSourceConfig | null {
		if (ds.source_type === 'file') {
			return ds.config as unknown as FileDataSourceConfig;
		}
		if (ds.source_type === 'iceberg') {
			const source = (ds.config as Record<string, unknown>)?.source as
				| Record<string, unknown>
				| undefined;
			if (source?.source_type === 'file') {
				return source as unknown as FileDataSourceConfig;
			}
		}
		return null;
	}

	function isCsv(ds: DataSource): boolean {
		return getFileSource(ds)?.file_type === 'csv';
	}

	function isExcel(ds: DataSource): boolean {
		return getFileSource(ds)?.file_type === 'excel';
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

	function isExcelConfigEqual(a: typeof excelConfig, b: typeof excelConfig): boolean {
		return (
			a.sheet_name === b.sheet_name &&
			a.table_name === b.table_name &&
			a.named_range === b.named_range &&
			a.cell_range === b.cell_range &&
			a.start_row === b.start_row &&
			a.start_col === b.start_col &&
			a.end_col === b.end_col &&
			a.end_row === b.end_row &&
			a.has_header === b.has_header
		);
	}

	function handleExcelConfigUpdate(value: typeof excelConfig) {
		if (isExcelConfigEqual(value, excelConfig)) return;
		excelConfig = value;
		hasChanges = true;
	}

	async function handleSave() {
		if (!datasourceQuery.data) return;

		const update: { name: string; config: Record<string, unknown> } = { name, config: {} };

		if (isCsv(datasourceQuery.data)) {
			const csvOptions = {
				delimiter: csvConfig.delimiter,
				quote_char: csvConfig.quote_char,
				has_header: csvConfig.has_header,
				skip_rows: csvConfig.skip_rows,
				encoding: csvConfig.encoding
			};
			if (datasourceQuery.data.source_type === 'iceberg') {
				const existingSource = (datasourceQuery.data.config as Record<string, unknown>)?.source as
					| Record<string, unknown>
					| undefined;
				update.config = {
					...datasourceQuery.data.config,
					source: { ...existingSource, csv_options: csvOptions }
				};
			} else {
				update.config = {
					...datasourceQuery.data.config,
					csv_options: csvOptions
				};
			}
		} else if (isExcel(datasourceQuery.data)) {
			const excelOptions = {
				sheet_name: excelConfig.sheet_name || null,
				table_name: excelConfig.table_name || null,
				named_range: excelConfig.named_range || null,
				cell_range: excelConfig.cell_range || null,
				start_row: excelConfig.start_row,
				start_col: excelConfig.start_col,
				end_col: excelConfig.end_col,
				end_row: excelConfig.end_row,
				has_header: excelConfig.has_header
			};
			if (datasourceQuery.data.source_type === 'iceberg') {
				const existingSource = (datasourceQuery.data.config as Record<string, unknown>)?.source as
					| Record<string, unknown>
					| undefined;
				update.config = {
					...datasourceQuery.data.config,
					source: { ...existingSource, ...excelOptions }
				};
			} else {
				update.config = {
					...datasourceQuery.data.config,
					...excelOptions
				};
			}
		} else if (isFile(datasourceQuery.data)) {
			update.config = { ...datasourceQuery.data.config };
		}

		await updateMutation.mutateAsync(update);
		hasChanges = false;

		if (update.config && ds.source_type === 'iceberg') {
			const source = (ds.config as Record<string, unknown>)?.source as
				| Record<string, unknown>
				| undefined;
			const sourceType = source?.source_type as string | undefined;
			if (sourceType === 'database' || sourceType === 'file') {
				const refreshResult = await refreshDatasource(ds.id);
				if (refreshResult.isErr()) {
					refreshError = refreshResult.error.message || 'Failed to re-ingest datasource';
					return;
				}
				queryClient.invalidateQueries({ queryKey: ['datasource', ds.id] });
				queryClient.invalidateQueries({ queryKey: ['datasource-schema', ds.id] });
				queryClient.invalidateQueries({ queryKey: ['datasource-preview', ds.id] });
				queryClient.invalidateQueries({ queryKey: ['datasources'] });
				queryClient.invalidateQueries({ queryKey: ['datasource-runs', ds.id] });
			}
		}
	}

	async function handleRefresh() {
		refreshError = null;
		isRefreshing = true;
		const previousColumns = new Map(columns.map((col) => [col.name, col.dtype]));

		if (datasource.source_type === 'analysis') {
			refreshError = 'Schema refresh is unavailable for analysis datasources';
			isRefreshing = false;
			return;
		}
		try {
			const config = datasource.config as Record<string, unknown> | null;
			const source = config?.source as Record<string, unknown> | undefined;
			if (datasource.source_type === 'iceberg' && source?.source_type === 'database') {
				const refreshResult = await refreshDatasource(datasource.id);
				if (refreshResult.isErr()) {
					throw new Error(refreshResult.error.message);
				}
			}
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

	const healthChecks = $derived(healthChecksQuery.data ?? []);
	const activeHealthChecks = $derived(healthChecks.filter((hc) => hc.enabled));
	const healthStatus = $derived.by(() => {
		const results = healthResultsQuery.data ?? [];
		if (activeHealthChecks.length === 0 || results.length === 0) return 'none';
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local Map for computation, not reactive state
		const latestPerCheck = new Map<string, boolean>();
		for (const r of results) {
			if (!latestPerCheck.has(r.healthcheck_id)) {
				latestPerCheck.set(r.healthcheck_id, r.passed);
			}
		}
		for (const passed of latestPerCheck.values()) {
			if (!passed) return 'failing';
		}
		return 'passing';
	});
	const ds = $derived(datasourceQuery.data ?? datasource);
	const csv = $derived(isCsv(ds));
	const excel = $derived(isExcel(ds));
	const runs = $derived(runsQuery.data ?? []);
	const filteredRuns = $derived.by(() => {
		if (showPreviews) return runs;
		return runs.filter((run) => run.kind !== 'preview');
	});
	const isOutputDatasource = $derived(ds.created_by === 'analysis');
	const scheduleAnalysisId = $derived(
		isOutputDatasource
			? (ds.created_by_analysis_id ?? (ds.config?.analysis_id as string | undefined) ?? null)
			: null
	);

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
			{#if filteredRuns.length > 0}
				<span class="ml-1 text-fg-tertiary">({filteredRuns.length})</span>
			{/if}
		</button>
		<button
			class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
			class:active={activeTab === 'health'}
			onclick={() => (activeTab = 'health')}
		>
			Health Checks
			{#if activeHealthChecks.length > 0}
				<span class="ml-1 text-fg-tertiary">({activeHealthChecks.length})</span>
				{#if healthStatus === 'passing'}
					<span class="ml-1 inline-block h-2 w-2 bg-success-fg" title="All checks passing"></span>
				{:else if healthStatus === 'failing'}
					<span class="ml-1 inline-block h-2 w-2 bg-error-fg" title="Some checks failing"></span>
				{:else}
					<span class="ml-1 inline-block h-2 w-2 bg-fg-muted" title="No results yet"></span>
				{/if}
			{/if}
		</button>
		{#if scheduleAnalysisId}
			<button
				class="tab -mb-px bg-transparent border-b-2 border-transparent px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg-secondary"
				class:active={activeTab === 'schedules'}
				onclick={() => (activeTab = 'schedules')}
			>
				Schedules
			</button>
		{/if}
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
									<FileTypeBadge sourceType={ds.source_type} size="sm" />
								{/if}
							</div>
							{#if ds.is_hidden}
								<div class="flex items-center gap-1.5">
									<span
										class="bg-warning-bg border border-warning-fg/20 px-1.5 py-0.5 text-[10px] uppercase font-medium text-warning-fg"
									>
										Hidden
									</span>
								</div>
							{/if}
						</div>

						<!-- Provenance -->
						<div class="flex items-center gap-2">
							<span class="uppercase tracking-wide text-fg-muted">Source</span>
							{#if ds.created_by === 'analysis'}
								<span class="inline-flex items-center gap-1 text-accent-primary">
									<GitBranch size={12} />
									<span class="font-medium">Analysis</span>
								</span>
								{#if ds.created_by_analysis_id}
									<a
										href={resolve(`/analysis/${ds.created_by_analysis_id}` as '/')}
										class="text-accent-primary hover:underline font-mono text-[10px]"
									>
										Open Analysis
									</a>
								{/if}
							{:else}
								<span class="inline-flex items-center gap-1 text-fg-secondary">
									<Upload size={12} />
									<span class="font-medium">Imported</span>
								</span>
							{/if}
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

						<!-- Metadata Path for Iceberg -->
						{#if isIceberg(ds)}
							{@const config = ds.config as unknown as IcebergDataSourceConfig}
							<div class="flex flex-col gap-1">
								<span class="uppercase tracking-wide text-fg-muted">Location</span>
								<span class="break-all text-fg-secondary font-mono">{config.metadata_path}</span>
							</div>
							<div class="flex flex-col gap-1">
								<span class="uppercase tracking-wide text-fg-muted">Branch</span>
								<span class="break-all text-fg-secondary font-mono"
									>{config.branch ?? 'master'}</span
								>
								<span class="text-[10px] text-fg-tertiary">Input branch for this datasource</span>
							</div>
							{#if config.source}
								{@const fileSource = config.source as Record<string, unknown>}
								<div class="border-t border-tertiary pt-2 mt-1 flex flex-col gap-2">
									<span class="text-[10px] uppercase tracking-wider text-fg-muted font-semibold"
										>Original Source</span
									>
									<div class="flex items-center gap-2">
										<span class="uppercase tracking-wide text-fg-muted">Type</span>
										<FileTypeBadge
											path={typeof fileSource.file_path === 'string' ? fileSource.file_path : ''}
											size="sm"
										/>
									</div>
									{#if typeof fileSource.file_path === 'string'}
										<div class="flex flex-col gap-1">
											<span class="uppercase tracking-wide text-fg-muted">File</span>
											<span class="break-all text-fg-secondary font-mono"
												>{fileSource.file_path}</span
											>
										</div>
									{/if}
								</div>
							{/if}
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
								class="grid grid-cols-[24px_1fr_140px] items-center gap-x-2 px-3 py-1.5 hover:bg-hover cursor-pointer"
								class:border-t={index > 0}
								class:border-tertiary={index > 0}
								role="button"
								tabindex="0"
								onclick={() => {
									statsColumn = column.name;
									statsOpen = true;
								}}
								onkeydown={(e) => {
									if (e.key === 'Enter' || e.key === ' ') {
										statsColumn = column.name;
										statsOpen = true;
									}
								}}
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
			{@const fileSource = getFileSource(ds)}
			<div class="flex flex-col gap-4">
				<ExcelTableSelector
					mode="config"
					filePath={fileSource?.file_path ?? null}
					initialConfig={excelConfig}
					disabled={updateMutation.isPending}
					onConfigChange={handleExcelConfigUpdate}
				/>
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
				{#if !fileSource?.file_path}
					<p class="m-0 text-xs text-fg-muted">
						No original file path available for Excel preview.
					</p>
				{/if}
			</div>
		{:else if activeTab === 'runs'}
			<div class="flex flex-col gap-3">
				<button
					class="btn-ghost btn-sm border border-tertiary text-xs w-fit"
					onclick={() => (showPreviews = !showPreviews)}
					aria-pressed={showPreviews}
				>
					{#if showPreviews}
						<EyeOff size={12} />
						Hide previews
					{:else}
						<Eye size={12} />
						Show previews
					{/if}
				</button>
				{#if runsQuery.isLoading}
					<div class="flex flex-col items-center justify-center gap-3 py-8 text-fg-muted">
						<Loader size={24} class="spin" />
						<p class="text-sm">Loading runs...</p>
					</div>
				{:else if runsQuery.isError}
					<div class="error-box flex items-start gap-3">
						<CircleAlert size={20} />
						<div class="flex flex-col gap-1">
							<p class="m-0 font-semibold">Failed to load runs</p>
							<p class="m-0 text-sm opacity-80">
								{runsQuery.error instanceof Error ? runsQuery.error.message : 'Unknown error'}
							</p>
						</div>
					</div>
				{:else if filteredRuns.length === 0}
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
						{#each filteredRuns as run, index (run.id)}
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
											class="text-[10px] px-1.5 py-0.5 bg-accent-bg text-accent-primary"
											title="This datasource was created from this export"
										>
											CREATED
										</span>
									{:else if dsTag === 'updated'}
										<span
											class="text-[10px] px-1.5 py-0.5 bg-warning-bg text-warning-fg"
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
					{#if filteredRuns.length >= 50}
						<p class="text-xs text-fg-tertiary text-center">
							Showing last 50 runs.
						<a
							href="{resolve('/monitoring')}?datasource_id={datasource.id}"
							class="text-accent-primary hover:underline"
						>
								View all runs
							</a>
						</p>
					{/if}
				{/if}
			</div>
		{:else if activeTab === 'health'}
			<HealthChecksManager datasourceId={datasource.id} compact />
		{:else if activeTab === 'schedules'}
			<ScheduleManager datasourceId={datasource.id} compact />
		{/if}
	</div>
</div>

<ColumnStatsPanel
	datasourceId={datasource.id}
	columnName={statsColumn}
	open={statsOpen}
	datasourceConfig={datasource.config as Record<string, unknown>}
	onClose={() => {
		statsOpen = false;
		statsColumn = null;
	}}
/>
