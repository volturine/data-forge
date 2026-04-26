<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import {
		getDatasource,
		getDatasourceSchema,
		refreshDatasource,
		updateDatasource,
		updateDatasourceColumnDescriptions
	} from '$lib/api/datasource';
	import { type EngineRun } from '$lib/api/engine-runs';
	import { EngineRunsStore } from '$lib/stores/engine-runs.svelte';
	import { listHealthChecks, listHealthCheckResults } from '$lib/api/healthcheck';
	import {
		Save,
		Loader,
		CircleAlert,
		RefreshCw,
		Pencil,
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
		DatabaseDataSource,
		FileDataSource,
		IcebergDataSource,
		SchemaInfo,
		ColumnSchema,
		FileDataSourceConfig
	} from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import ExcelTableSelector from '$lib/components/common/ExcelTableSelector.svelte';
	import ColumnStatsPanel from '$lib/components/datasources/ColumnStatsPanel.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { formatDateDisplay } from '$lib/utils/datetime';
	import { resolveColumnType } from '$lib/utils/column-types';
	import { css, input, tabButton, chip, emptyText } from '$lib/styles/panda';

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

	const engineRunsStore = new EngineRunsStore();
	// Network: fetch datasource runs when the datasource changes.
	$effect(() => {
		if (!datasource.id) return;
		engineRunsStore.load({ datasource_id: datasource.id, limit: 50 });
		return () => engineRunsStore.close();
	});

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
		mutationFn: async (update: {
			name: string;
			description: string | null;
			config?: Record<string, unknown>;
		}) => {
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
	let description = $state('');
	let columns = $state<ColumnSchema[]>([]);
	let hasChanges = $state(false);
	let configDirty = $state(false);
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
	let editingColumn = $state<string | null>(null);
	let descriptionDraft = $state('');
	let descriptionError = $state<string | null>(null);
	let descriptionExpanded = $state<Record<string, boolean>>({});
	let currentDatasourceId = $state<string | null>(null);

	const descriptionMutation = createMutation(() => ({
		mutationFn: async (payload: { columnName: string; description: string | null }) => {
			const result = await updateDatasourceColumnDescriptions(datasource.id, [
				{ column_name: payload.columnName, description: payload.description }
			]);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: (schema) => {
			setSchema(schema);
			queryClient.setQueryData(['datasource-schema', datasource.id], schema);
			queryClient.invalidateQueries({ queryKey: ['datasource-schema', datasource.id] });
			editingColumn = null;
			descriptionDraft = '';
			descriptionError = null;
			onSave?.();
		}
	}));

	// Subscription: $derived can't reset state only when the selected datasource changes.
	$effect(() => {
		const ds = datasource;
		if (!ds) return;
		if (currentDatasourceId === ds.id) return;
		currentDatasourceId = ds.id;

		// Reset all state for new datasource
		name = ds.name;
		description = ds.description ?? '';
		columns = [];
		hasChanges = false;
		configDirty = false;
		isRefreshing = false;
		refreshError = null;
		schemaChanged = false;
		schemaDiff = null;
		activeTab = 'general';
		statsOpen = false;
		statsColumn = null;
		editingColumn = null;
		descriptionDraft = '';
		descriptionError = null;
		descriptionExpanded = {};

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
			const cellRangeValue = fileSource.cell_range;
			const cellRange = typeof cellRangeValue === 'string' ? cellRangeValue : '';
			const sheetValue = fileSource.sheet_name;
			const sheetName = typeof sheetValue === 'string' ? sheetValue : '';
			const tableValue = fileSource.table_name;
			const tableName = typeof tableValue === 'string' ? tableValue : '';
			const rangeValue = fileSource.named_range;
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

	function getSelectedDescription(name: string | null): string | null {
		if (!name) return null;
		return columns.find((column) => column.name === name)?.description ?? null;
	}

	function isDescriptionExpanded(name: string): boolean {
		return descriptionExpanded[name] ?? false;
	}

	function isDescriptionLong(value: string | null | undefined): boolean {
		return (value?.length ?? 0) > 140;
	}

	function getDescriptionPreview(value: string | null | undefined, expanded: boolean): string {
		if (!value) return 'No description';
		if (expanded || !isDescriptionLong(value)) return value;
		return `${value.slice(0, 140).trimEnd()}...`;
	}

	function toggleDescription(name: string) {
		descriptionExpanded = { ...descriptionExpanded, [name]: !isDescriptionExpanded(name) };
	}

	function startEditingDescription(column: ColumnSchema) {
		editingColumn = column.name;
		descriptionDraft = column.description ?? '';
		descriptionError = null;
	}

	function cancelEditingDescription() {
		editingColumn = null;
		descriptionDraft = '';
		descriptionError = null;
	}

	async function saveDescription(columnName: string) {
		descriptionError = null;
		try {
			await descriptionMutation.mutateAsync({
				columnName,
				description: descriptionDraft
			});
		} catch (error) {
			descriptionError = error instanceof Error ? error.message : 'Failed to save description';
		}
	}

	function getFileSource(ds: DataSource): FileDataSourceConfig | null {
		if (ds.source_type === 'file') {
			return ds.config;
		}
		if (ds.source_type === 'iceberg') {
			const source = ds.config.source as Record<string, unknown> | undefined;
			if (source?.source_type === 'file') {
				return source as FileDataSourceConfig;
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

	function isDatabase(ds: DataSource): ds is DatabaseDataSource {
		return ds.source_type === 'database';
	}

	function isIceberg(ds: DataSource): boolean {
		return ds.source_type === 'iceberg';
	}

	function handleNameChange(newName: string) {
		name = newName;
		hasChanges = true;
	}

	function handleDescriptionChange(newDescription: string) {
		description = newDescription;
		hasChanges = true;
	}

	function handleCsvConfigChange<K extends keyof typeof csvConfig>(
		key: K,
		value: (typeof csvConfig)[K]
	) {
		csvConfig = { ...csvConfig, [key]: value };
		hasChanges = true;
		configDirty = true;
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
		configDirty = true;
	}

	const PROTECTED_CONFIG_KEYS = [
		'snapshot_id',
		'snapshot_timestamp_ms',
		'current_snapshot_id',
		'current_snapshot_timestamp_ms',
		'time_travel_snapshot_id',
		'time_travel_snapshot_timestamp_ms',
		'time_travel_ui'
	];

	function stripProtectedKeys(config: Record<string, unknown>): Record<string, unknown> {
		const cleaned = { ...config };
		for (const key of PROTECTED_CONFIG_KEYS) {
			delete cleaned[key];
		}
		return cleaned;
	}

	async function handleSave() {
		if (!datasourceQuery.data) return;

		const update: { name: string; description: string | null; config?: Record<string, unknown> } = {
			name,
			description
		};

		if (configDirty) {
			if (isCsv(datasourceQuery.data)) {
				const csvOptions = {
					delimiter: csvConfig.delimiter,
					quote_char: csvConfig.quote_char,
					has_header: csvConfig.has_header,
					skip_rows: csvConfig.skip_rows,
					encoding: csvConfig.encoding
				};
				if (datasourceQuery.data.source_type === 'iceberg') {
					const existingSource = (datasourceQuery.data.config as Record<string, unknown>)
						?.source as Record<string, unknown> | undefined;
					update.config = stripProtectedKeys({
						...datasourceQuery.data.config,
						source: { ...existingSource, csv_options: csvOptions }
					});
				} else {
					update.config = stripProtectedKeys({
						...datasourceQuery.data.config,
						csv_options: csvOptions
					});
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
					const existingSource = (datasourceQuery.data.config as Record<string, unknown>)
						?.source as Record<string, unknown> | undefined;
					update.config = stripProtectedKeys({
						...datasourceQuery.data.config,
						source: { ...existingSource, ...excelOptions }
					});
				} else {
					update.config = stripProtectedKeys({
						...datasourceQuery.data.config,
						...excelOptions
					});
				}
			} else if (isFile(datasourceQuery.data)) {
				update.config = stripProtectedKeys({ ...datasourceQuery.data.config });
			}
		}

		await updateMutation.mutateAsync(update);
		hasChanges = false;
		configDirty = false;

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
			const reingested =
				datasource.source_type === 'iceberg' &&
				(source?.source_type === 'database' || source?.source_type === 'file');
			if (reingested) {
				const refreshResult = await refreshDatasource(datasource.id);
				if (refreshResult.isErr()) {
					throw new Error(refreshResult.error.message);
				}
			}
			const result = await getDatasourceSchema(datasource.id, { refresh: !reingested });
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
	const runs = $derived(engineRunsStore.runs);
	const filteredRuns = $derived.by(() => {
		if (showPreviews) return runs;
		return runs.filter((run: EngineRun) => run.kind !== 'preview');
	});
	const isOutputDatasource = $derived(ds.created_by === 'analysis');
	const scheduleAnalysisId = $derived(
		isOutputDatasource
			? (ds.created_by_analysis_id ?? (ds.config?.analysis_id as string | undefined) ?? null)
			: null
	);
	const rawSchedulable = $derived.by(() => {
		if (ds.source_type !== 'iceberg') return false;
		if (ds.created_by === 'analysis') return false;
		const source = (ds.config as Record<string, unknown>)?.source as
			| Record<string, unknown>
			| undefined;
		if (!source) return false;
		const st = source.source_type;
		return st === 'file' || st === 'database';
	});

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

<div class={css({ backgroundColor: 'bg.secondary' })} data-ds-config={datasource.id}>
	{#if updateMutation.isError}
		<Callout tone="error">
			<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
				<CircleAlert size={20} />
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
					<p class={css({ margin: '0', fontWeight: 'semibold' })}>Error saving changes</p>
					<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
						{updateMutation.error instanceof Error ? updateMutation.error.message : 'Unknown error'}
					</p>
				</div>
			</div>
		</Callout>
	{/if}

	{#if updateMutation.isSuccess}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				margin: '4',
				marginBottom: '0',
				gap: '2',
				paddingX: '3',
				paddingY: '2.5',
				border: 'none',
				borderLeftWidth: '2',
				fontSize: 'xs',
				lineHeight: 'normal',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.success',
				color: 'fg.success',
				borderWidth: '1',
				borderColor: 'border.success'
			})}
		>
			<p class={css({ margin: '0' })}>Changes saved successfully!</p>
		</div>
	{/if}

	<div
		class={css({
			display: 'flex',
			gap: '0',
			paddingX: '4',
			paddingTop: '3'
		})}
		role="tablist"
		aria-label="Datasource configuration"
	>
		<button
			class={tabButton({ active: activeTab === 'general' })}
			onclick={() => (activeTab = 'general')}
			role="tab"
			aria-selected={activeTab === 'general'}
		>
			General
		</button>
		<button
			class={tabButton({ active: activeTab === 'schema' })}
			onclick={() => (activeTab = 'schema')}
			role="tab"
			aria-selected={activeTab === 'schema'}
		>
			Schema
		</button>
		{#if csv}
			<button
				class={tabButton({ active: activeTab === 'csv' })}
				onclick={() => (activeTab = 'csv')}
				role="tab"
				aria-selected={activeTab === 'csv'}
			>
				CSV
			</button>
		{/if}
		{#if excel}
			<button
				class={tabButton({ active: activeTab === 'excel' })}
				onclick={() => (activeTab = 'excel')}
				role="tab"
				aria-selected={activeTab === 'excel'}
			>
				Excel
			</button>
		{/if}
		<button
			class={tabButton({ active: activeTab === 'runs' })}
			onclick={() => (activeTab = 'runs')}
			role="tab"
			aria-selected={activeTab === 'runs'}
		>
			Runs
			{#if filteredRuns.length > 0}
				<span class={css({ marginLeft: '1', color: 'fg.tertiary' })}>({filteredRuns.length})</span>
			{/if}
		</button>
		<button
			class={tabButton({ active: activeTab === 'health' })}
			onclick={() => (activeTab = 'health')}
			role="tab"
			aria-selected={activeTab === 'health'}
		>
			Health Checks
			{#if activeHealthChecks.length > 0}
				<span class={css({ marginLeft: '1', color: 'fg.tertiary' })}
					>({activeHealthChecks.length})</span
				>
				{#if healthStatus === 'passing'}
					<span
						class={css({
							marginLeft: '1',
							display: 'inline-block',
							height: 'dot',
							width: 'dot',
							backgroundColor: 'fg.success'
						})}
						title="All checks passing"
					></span>
				{:else if healthStatus === 'failing'}
					<span
						class={css({
							marginLeft: '1',
							display: 'inline-block',
							height: 'dot',
							width: 'dot',
							backgroundColor: 'fg.error'
						})}
						title="Some checks failing"
					></span>
				{:else}
					<span
						class={css({
							marginLeft: '1',
							display: 'inline-block',
							height: 'dot',
							width: 'dot',
							backgroundColor: 'bg.indicator'
						})}
						title="No results yet"
					></span>
				{/if}
			{/if}
		</button>
		{#if scheduleAnalysisId || rawSchedulable}
			<button
				class={tabButton({ active: activeTab === 'schedules' })}
				onclick={() => (activeTab = 'schedules')}
				role="tab"
				aria-selected={activeTab === 'schedules'}
			>
				Schedules
			</button>
		{/if}
	</div>

	<div class={css({ padding: '4' })}>
		{#if activeTab === 'general'}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label
						for="datasource-name-{datasource.id}"
						class={css({
							display: 'block',
							fontSize: 'xs',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '1.5'
						})}>Name</label
					>
					<input
						id="datasource-name-{datasource.id}"
						type="text"
						value={name}
						oninput={(e) => handleNameChange(e.currentTarget.value)}
						placeholder="Data source name"
						class={input()}
					/>
				</div>

				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label
						for="datasource-description-{datasource.id}"
						class={css({
							display: 'block',
							fontSize: 'xs',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '1.5'
						})}>Description</label
					>
					<textarea
						id="datasource-description-{datasource.id}"
						value={description}
						oninput={(e) => handleDescriptionChange(e.currentTarget.value)}
						placeholder="Add context about what this dataset represents, when to use it, and any caveats."
						rows="5"
						maxlength="4000"
						class={css({
							width: 'full',
							fontSize: 'sm2',
							color: 'fg.primary',
							backgroundColor: 'bg.primary',
							borderWidth: '1',
							borderRadius: '0',
							paddingX: '3.5',
							paddingY: '2.25',
							resize: 'vertical',
							transitionProperty: 'border-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_focus: { outline: 'none' },
							_focusVisible: { borderColor: 'border.accent' },
							_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
							_placeholder: { color: 'fg.muted' }
						})}
					></textarea>
					{#if description.trim().length === 0}
						<p class={emptyText({ size: 'inline' })}>No description added yet.</p>
					{/if}
				</div>

				<div class={css({ paddingTop: '4' })}>
					<h3
						class={css({
							margin: '0',
							marginBottom: '3',
							fontSize: 'xs',
							fontWeight: 'semibold',
							color: 'fg.secondary'
						})}
					>
						Source Information
					</h3>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '3', fontSize: 'xs' })}>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
							<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Type</span
								>
								{#if isFile(ds)}
									{@const config = (ds as FileDataSource).config}
									<FileTypeBadge path={config.file_path} size="sm" />
								{:else}
									<FileTypeBadge sourceType={ds.source_type} size="sm" />
								{/if}
							</div>
							{#if ds.is_hidden}
								<div class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
									<span class={chip({ tone: 'warning' })}> Hidden </span>
								</div>
							{/if}
						</div>

						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<span
								class={css({
									textTransform: 'uppercase',
									letterSpacing: 'wide',
									color: 'fg.muted'
								})}>Source</span
							>
							{#if ds.created_by === 'analysis'}
								<span
									class={css({
										display: 'inline-flex',
										alignItems: 'center',
										gap: '1',
										color: 'accent.primary'
									})}
								>
									<GitBranch size={12} />
									<span class={css({ fontWeight: 'medium' })}>Analysis</span>
								</span>
								{#if ds.created_by_analysis_id}
									<a
										href={resolve(`/analysis/${ds.created_by_analysis_id}` as '/')}
										class={css({
											color: 'accent.primary',
											_hover: { textDecoration: 'underline' },
											fontFamily: 'mono',
											fontSize: '2xs'
										})}
									>
										Open Analysis
									</a>
								{/if}
							{:else}
								<span
									class={css({
										display: 'inline-flex',
										alignItems: 'center',
										gap: '1',
										color: 'fg.secondary'
									})}
								>
									<Upload size={12} />
									<span class={css({ fontWeight: 'medium' })}>Imported</span>
								</span>
							{/if}
						</div>

						<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
							<span
								class={css({
									textTransform: 'uppercase',
									letterSpacing: 'wide',
									color: 'fg.muted'
								})}>Datasource ID</span
							>
							<span
								class={css({
									wordBreak: 'break-all',
									color: 'fg.secondary',
									fontFamily: 'mono'
								})}>{ds.id}</span
							>
						</div>

						{#if isFile(ds)}
							{@const config = (ds as FileDataSource).config}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Location</span
								>
								<span
									class={css({
										wordBreak: 'break-all',
										color: 'fg.secondary',
										fontFamily: 'mono'
									})}>{config.file_path}</span
								>
							</div>
						{/if}

						{#if isDatabase(ds)}
							{@const config = ds.config}
							{#if config.connection_string}
								<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
									<span
										class={css({
											textTransform: 'uppercase',
											letterSpacing: 'wide',
											color: 'fg.muted'
										})}>Location</span
									>
									<span
										class={css({
											wordBreak: 'break-all',
											color: 'fg.secondary',
											fontFamily: 'mono'
										})}>{config.connection_string}</span
									>
								</div>
							{/if}
						{/if}

						{#if isIceberg(ds)}
							{@const config = (ds as IcebergDataSource).config}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Location</span
								>
								<span
									class={css({
										wordBreak: 'break-all',
										color: 'fg.secondary',
										fontFamily: 'mono'
									})}>{config.metadata_path}</span
								>
							</div>
							{#if config.source}
								{@const fileSource = config.source as Record<string, unknown>}
								<div
									class={css({
										paddingTop: '2',
										marginTop: '1',
										display: 'flex',
										flexDirection: 'column',
										gap: '2'
									})}
								>
									<span
										class={css({
											fontSize: '2xs',
											textTransform: 'uppercase',
											letterSpacing: 'wider',
											color: 'fg.muted',
											fontWeight: 'semibold'
										})}>Original Source</span
									>
									<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
										<span
											class={css({
												textTransform: 'uppercase',
												letterSpacing: 'wide',
												color: 'fg.muted'
											})}>Type</span
										>
										<FileTypeBadge
											path={typeof fileSource.file_path === 'string' ? fileSource.file_path : ''}
											size="sm"
										/>
									</div>
									{#if typeof fileSource.file_path === 'string'}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
											<span
												class={css({
													textTransform: 'uppercase',
													letterSpacing: 'wide',
													color: 'fg.muted'
												})}>File</span
											>
											<span
												class={css({
													wordBreak: 'break-all',
													color: 'fg.secondary',
													fontFamily: 'mono'
												})}>{fileSource.file_path}</span
											>
										</div>
									{/if}
								</div>
							{/if}
						{/if}

						<div class={css({ display: 'flex', alignItems: 'center', gap: '4' })}>
							<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
								<span
									class={css({
										textTransform: 'uppercase',
										letterSpacing: 'wide',
										color: 'fg.muted'
									})}>Created</span
								>
								<span class={css({ fontWeight: 'medium' })}>{formatDateDisplay(ds.created_at)}</span
								>
							</div>
							{#if schemaQuery.data}
								<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
									<span
										class={css({
											textTransform: 'uppercase',
											letterSpacing: 'wide',
											color: 'fg.muted'
										})}>Rows</span
									>
									<span class={css({ fontWeight: 'medium' })}
										>{schemaQuery.data.row_count?.toLocaleString() ?? 'Unknown'}</span
									>
								</div>
								<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
									<span
										class={css({
											textTransform: 'uppercase',
											letterSpacing: 'wide',
											color: 'fg.muted'
										})}>Columns</span
									>
									<span class={css({ fontWeight: 'medium' })}
										>{schemaQuery.data.columns.length}</span
									>
								</div>
							{/if}
						</div>
					</div>
				</div>

				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						paddingTop: '4',
						justifyContent: 'space-between',
						gap: '3'
					})}
				>
					<button
						class={css({
							borderWidth: '1',
							backgroundColor: 'transparent',
							color: 'fg.primary',
							'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.secondary' },
							display: 'flex',
							alignItems: 'center',
							gap: '2'
						})}
						onclick={handleRefresh}
						disabled={isRefreshing || updateMutation.isPending}
					>
						{#if isRefreshing}
							<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
							Refreshing...
						{:else}
							<RefreshCw size={16} />
							Refresh
						{/if}
					</button>
					{#if hasChanges}
						<button
							class={css({
								borderWidth: '1',
								backgroundColor: 'accent.primary',
								color: 'fg.inverse',
								'&:hover:not(:disabled)': { opacity: '0.9' },
								display: 'flex',
								alignItems: 'center',
								gap: '2'
							})}
							onclick={handleSave}
							disabled={updateMutation.isPending}
						>
							{#if updateMutation.isPending}
								<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
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
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
				{#if refreshError}
					<Callout tone="error">
						<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
							<CircleAlert size={20} />
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<p class={css({ margin: '0', fontWeight: 'semibold' })}>Refresh failed</p>
								<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>{refreshError}</p>
							</div>
						</div>
					</Callout>
				{/if}
				{#if schemaChanged && schemaDiff}
					<Callout tone="warn">
						<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
							<CircleAlert size={20} />
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<p class={css({ margin: '0', fontWeight: 'semibold' })}>Schema changed in source</p>
								{#if schemaDiff.added.length > 0}
									<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
										Added: {schemaDiff.added.join(', ')}
									</p>
								{/if}
								{#if schemaDiff.removed.length > 0}
									<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
										Removed: {schemaDiff.removed.join(', ')}
									</p>
								{/if}
								{#if schemaDiff.types.length > 0}
									<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
										Type changes: {schemaDiff.types.join(', ')}
									</p>
								{/if}
							</div>
						</div>
					</Callout>
				{/if}
				{#if schemaQuery.isLoading}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							flexDirection: 'column',
							justifyContent: 'center',
							gap: '3',
							paddingY: '8',
							color: 'fg.muted'
						})}
					>
						<Loader size={24} class={css({ animation: 'spin 1s linear infinite' })} />
						<p class={css({ fontSize: 'sm' })}>Loading schema...</p>
					</div>
				{:else if columns.length > 0}
					<div
						class={css({
							borderWidth: '1'
						})}
					>
						<div
							class={css({
								display: 'grid',
								gridTemplateColumns: '24px minmax(0, 1fr) 140px minmax(0, 1.6fr)',
								alignItems: 'center',
								columnGap: '2',
								backgroundColor: 'bg.tertiary',
								paddingX: '3',
								paddingY: '2',
								fontSize: 'xs',
								fontWeight: 'semibold',
								textTransform: 'uppercase',
								letterSpacing: 'wide',
								color: 'fg.muted',
								borderBottomWidth: '1'
							})}
						>
							<span>#</span>
							<span>Column</span>
							<span>Type</span>
							<span>Description</span>
						</div>
						{#each columns as column, index (index)}
							<div
								class={css(
									{
										display: 'grid',
										gridTemplateColumns: '24px minmax(0, 1fr) 140px minmax(0, 1.6fr)',
										alignItems: 'center',
										columnGap: '2',
										paddingX: '3',
										paddingY: '1.5',
										backgroundColor: 'transparent'
									},
									index > 0 && { borderTopWidth: '1' }
								)}
							>
								<span class={css({ fontSize: 'xs', color: 'fg.faint' })}>{index + 1}</span>
								<button
									type="button"
									class={css({
										fontSize: 'xs',
										textAlign: 'left',
										backgroundColor: 'transparent',
										borderColor: 'transparent',
										padding: '0',
										minWidth: '0',
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										_hover: { color: 'accent.primary' }
									})}
									data-schema-column={column.name}
									onclick={() => {
										statsColumn = column.name;
										statsOpen = true;
									}}
								>
									{column.name}
								</button>
								<div>
									<ColumnTypeBadge columnType={column.dtype} size="sm" showIcon={true} />
								</div>
								<div class={css({ minWidth: '0' })}>
									{#if editingColumn === column.name}
										<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
											<textarea
												value={descriptionDraft}
												oninput={(e) => (descriptionDraft = e.currentTarget.value)}
												rows="4"
												maxlength="2000"
												class={css({
													width: 'full',
													fontSize: 'xs',
													paddingX: '2',
													paddingY: '1.5',
													borderWidth: '1',
													backgroundColor: 'bg.primary',
													resize: 'vertical',
													_focus: { outline: 'none' },
													_focusVisible: { borderColor: 'border.accent' }
												})}
											></textarea>
											<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
												<button
													type="button"
													class={css({
														borderWidth: '1',
														backgroundColor: 'accent.primary',
														color: 'fg.inverse',
														fontSize: 'xs',
														paddingX: '2',
														paddingY: '1'
													})}
													onclick={() => saveDescription(column.name)}
													disabled={descriptionMutation.isPending}
												>
													{#if descriptionMutation.isPending}
														Saving...
													{:else}
														Save
													{/if}
												</button>
												<button
													type="button"
													class={css({
														borderWidth: '1',
														backgroundColor: 'transparent',
														fontSize: 'xs',
														paddingX: '2',
														paddingY: '1'
													})}
													onclick={cancelEditingDescription}
													disabled={descriptionMutation.isPending}
												>
													Cancel
												</button>
												<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
													{descriptionDraft.length}/2000
												</span>
											</div>
											{#if descriptionError}
												<p class={css({ margin: '0', fontSize: '2xs', color: 'fg.error' })}>
													{descriptionError}
												</p>
											{/if}
										</div>
									{:else}
										<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '2' })}>
											<div
												class={css({
													flex: '1',
													minWidth: '0',
													fontSize: 'xs',
													color: column.description ? 'fg.primary' : 'fg.muted',
													whiteSpace: 'pre-wrap',
													wordBreak: 'break-word'
												})}
												data-schema-description={column.name}
											>
												{getDescriptionPreview(
													column.description ?? null,
													isDescriptionExpanded(column.name)
												)}
												{#if column.description && isDescriptionLong(column.description)}
													<button
														type="button"
														class={css({
															marginLeft: '1',
															padding: '0',
															borderColor: 'transparent',
															backgroundColor: 'transparent',
															fontSize: '2xs',
															color: 'accent.primary'
														})}
														onclick={() => toggleDescription(column.name)}
													>
														{#if isDescriptionExpanded(column.name)}
															Show less
														{:else}
															Show more
														{/if}
													</button>
												{/if}
											</div>
											<button
												type="button"
												class={css({
													display: 'inline-flex',
													alignItems: 'center',
													justifyContent: 'center',
													borderWidth: '1',
													backgroundColor: 'transparent',
													paddingX: '1.5',
													paddingY: '1',
													color: 'fg.secondary',
													_hover: { backgroundColor: 'bg.hover' }
												})}
												aria-label={`Edit description for ${column.name}`}
												onclick={() => startEditingDescription(column)}
											>
												<Pencil size={12} />
											</button>
										</div>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<div class={emptyText({ size: 'panel' })}>
						<p class={css({ margin: '0' })}>No schema information available.</p>
					</div>
				{/if}
			</div>
		{:else if activeTab === 'csv' && csv}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
				<h3 class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}>CSV Options</h3>

				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
						gap: '3'
					})}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
						<label
							for="csv-delimiter-{datasource.id}"
							class={css({
								display: 'block',
								fontSize: 'xs',
								fontWeight: 'medium',
								color: 'fg.secondary',
								textTransform: 'none',
								letterSpacing: 'normal',
								marginBottom: '1.5'
							})}>Delimiter</label
						>
						<select
							id="csv-delimiter-{datasource.id}"
							value={csvConfig.delimiter}
							onchange={(e) => handleCsvConfigChange('delimiter', e.currentTarget.value)}
							class={input()}
						>
							<option value=",">Comma (,)</option>
							<option value=";">Semicolon (;)</option>
							<option value="\t">Tab</option>
							<option value="|">Pipe (|)</option>
							<option value=" ">Space</option>
						</select>
					</div>

					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
						<label
							for="csv-quote-{datasource.id}"
							class={css({
								display: 'block',
								fontSize: 'xs',
								fontWeight: 'medium',
								color: 'fg.secondary',
								textTransform: 'none',
								letterSpacing: 'normal',
								marginBottom: '1.5'
							})}>Quote</label
						>
						<select
							id="csv-quote-{datasource.id}"
							value={csvConfig.quote_char}
							onchange={(e) => handleCsvConfigChange('quote_char', e.currentTarget.value)}
							class={input()}
						>
							<option value="&quot;">Double Quote (")</option>
							<option value="'">Single Quote (')</option>
							<option value="">None</option>
						</select>
					</div>

					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
						<label
							for="csv-encoding-{datasource.id}"
							class={css({
								display: 'block',
								fontSize: 'xs',
								fontWeight: 'medium',
								color: 'fg.secondary',
								textTransform: 'none',
								letterSpacing: 'normal',
								marginBottom: '1.5'
							})}>Encoding</label
						>
						<select
							id="csv-encoding-{datasource.id}"
							value={csvConfig.encoding}
							onchange={(e) => handleCsvConfigChange('encoding', e.currentTarget.value)}
							class={input()}
						>
							<option value="utf8">UTF-8</option>
							<option value="utf8-lossy">UTF-8 (lossy)</option>
							<option value="latin1">Latin-1</option>
							<option value="ascii">ASCII</option>
						</select>
					</div>

					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1.5' })}>
						<label
							for="csv-skip-rows-{datasource.id}"
							class={css({
								display: 'block',
								fontSize: 'xs',
								fontWeight: 'medium',
								color: 'fg.secondary',
								textTransform: 'none',
								letterSpacing: 'normal',
								marginBottom: '1.5'
							})}>Skip Rows</label
						>
						<input
							id="csv-skip-rows-{datasource.id}"
							type="number"
							min="0"
							value={csvConfig.skip_rows}
							oninput={(e) =>
								handleCsvConfigChange('skip_rows', parseInt(e.currentTarget.value) || 0)}
							class={input()}
						/>
					</div>
				</div>

				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<input
						id="csv-header-{datasource.id}"
						type="checkbox"
						checked={csvConfig.has_header}
						onchange={(e) => handleCsvConfigChange('has_header', e.currentTarget.checked)}
						class={css({ height: 'iconSm', width: 'iconSm', cursor: 'pointer' })}
					/>
					<label
						for="csv-header-{datasource.id}"
						class={css({
							display: 'block',
							fontSize: 'sm',
							fontWeight: 'medium',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							margin: '0'
						})}>First row is header</label
					>
				</div>

				{#if hasChanges}
					<button
						class={css({
							borderWidth: '1',
							backgroundColor: 'accent.primary',
							color: 'fg.inverse',
							'&:hover:not(:disabled)': { opacity: '0.9' },
							display: 'flex',
							alignItems: 'center',
							width: '100%',
							justifyContent: 'center',
							gap: '2'
						})}
						onclick={handleSave}
						disabled={updateMutation.isPending}
					>
						{#if updateMutation.isPending}
							<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
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
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
				<ExcelTableSelector
					mode="config"
					filePath={fileSource?.file_path ?? null}
					initialConfig={excelConfig}
					disabled={updateMutation.isPending}
					onConfigChange={handleExcelConfigUpdate}
				/>
				{#if hasChanges}
					<button
						class={css({
							borderWidth: '1',
							backgroundColor: 'accent.primary',
							color: 'fg.inverse',
							'&:hover:not(:disabled)': { opacity: '0.9' },
							display: 'flex',
							alignItems: 'center',
							width: '100%',
							justifyContent: 'center',
							gap: '2'
						})}
						onclick={handleSave}
						disabled={updateMutation.isPending}
					>
						{#if updateMutation.isPending}
							<Loader size={16} class={css({ animation: 'spin 1s linear infinite' })} />
							Saving...
						{:else}
							<Save size={16} />
							Save Changes
						{/if}
					</button>
				{/if}
				{#if !fileSource?.file_path}
					<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
						No original file path available for Excel preview.
					</p>
				{/if}
			</div>
		{:else if activeTab === 'runs'}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
				<button
					class={css({
						borderWidth: '1',
						backgroundColor: 'transparent',
						color: 'fg.secondary',
						borderColor: 'transparent',
						fontSize: 'xs',
						paddingX: '2',
						paddingY: '1',
						width: 'fit-content',
						'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})}
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
				{#if engineRunsStore.status === 'connecting'}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							flexDirection: 'column',
							justifyContent: 'center',
							gap: '3',
							paddingY: '8',
							color: 'fg.muted'
						})}
					>
						<Loader size={24} class={css({ animation: 'spin 1s linear infinite' })} />
						<p class={css({ fontSize: 'sm' })}>Loading runs...</p>
					</div>
				{:else if engineRunsStore.status === 'error'}
					<Callout tone="error">
						<div class={css({ display: 'flex', alignItems: 'flex-start', gap: '3' })}>
							<CircleAlert size={20} />
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<p class={css({ margin: '0', fontWeight: 'semibold' })}>Failed to load runs</p>
								<p class={css({ margin: '0', fontSize: 'sm', opacity: '0.8' })}>
									{engineRunsStore.error ?? 'Unknown error'}
								</p>
							</div>
						</div>
					</Callout>
				{:else if filteredRuns.length === 0}
					<div class={emptyText({ size: 'panel' })}>
						<p class={css({ margin: '0' })}>No engine runs associated with this datasource.</p>
						<p class={css({ margin: '0', marginTop: '1', color: 'fg.tertiary' })}>
							Runs will appear here when this datasource is used in analyses.
						</p>
					</div>
				{:else}
					<div
						class={css({
							borderWidth: '1'
						})}
					>
						<div
							class={css({
								display: 'grid',
								gridTemplateColumns: '1fr 80px 80px 100px',
								alignItems: 'center',
								columnGap: '2',
								backgroundColor: 'bg.tertiary',
								paddingX: '3',
								paddingY: '2',
								fontSize: 'xs',
								fontWeight: 'semibold',
								textTransform: 'uppercase',
								letterSpacing: 'wide',
								color: 'fg.muted',
								borderBottomWidth: '1'
							})}
						>
							<span>Type</span>
							<span>Status</span>
							<span>Duration</span>
							<span>Created</span>
						</div>
						{#each filteredRuns as run, index (run.id)}
							{@const dsTag = getDatasourceTag(run)}
							<div
								class={css(
									{
										display: 'grid',
										gridTemplateColumns: '1fr 80px 80px 100px',
										alignItems: 'center',
										columnGap: '2',
										paddingX: '3',
										paddingY: '2'
									},
									index > 0 && { borderTopWidth: '1' }
								)}
							>
								<div
									class={css({ display: 'flex', alignItems: 'center', gap: '2', fontSize: 'xs' })}
								>
									{#if (run.kind as string) === 'preview'}
										<Eye size={14} class={css({ flexShrink: '0', color: 'accent.primary' })} />
										<span>Preview</span>
									{:else if (run.kind as string) === 'datasource_create'}
										<Save size={14} class={css({ flexShrink: '0', color: 'accent.primary' })} />
										<span>Create</span>
									{:else if (run.kind as string) === 'datasource_update'}
										<RefreshCw size={14} class={css({ flexShrink: '0', color: 'fg.warning' })} />
										<span>Update</span>
									{:else}
										<Download size={14} class={css({ flexShrink: '0', color: 'fg.success' })} />
										<span>Export</span>
									{/if}
									{#if dsTag === 'created'}
										<span
											class={chip({ tone: 'accent' })}
											title="This datasource was created from this export"
										>
											CREATED
										</span>
									{:else if dsTag === 'updated'}
										<span
											class={chip({ tone: 'warning' })}
											title="This datasource was updated in this run"
										>
											UPDATED
										</span>
									{/if}
								</div>
								<div
									class={css({ display: 'flex', alignItems: 'center', gap: '1.5', fontSize: 'xs' })}
								>
									{#if run.status === 'success'}
										<CircleCheck size={14} class={css({ color: 'fg.success' })} />
										<span class={css({ color: 'fg.success' })}>Success</span>
									{:else}
										<CircleX size={14} class={css({ color: 'fg.error' })} />
										<span class={css({ color: 'fg.error' })}>Failed</span>
									{/if}
								</div>
								<span
									class={css({
										fontSize: 'xs',
										fontFamily: 'mono',
										color: 'fg.secondary'
									})}
								>
									{formatDuration(run.duration_ms)}
								</span>
								<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
									{formatDateDisplay(run.created_at)}
								</span>
							</div>
						{/each}
					</div>
					{#if filteredRuns.length >= 50}
						<p class={css({ fontSize: 'xs', color: 'fg.tertiary', textAlign: 'center' })}>
							Showing last 50 runs.
							<a
								href="{resolve('/monitoring')}?datasource_id={datasource.id}"
								class={css({ color: 'accent.primary', _hover: { textDecoration: 'underline' } })}
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
	columnDescription={getSelectedDescription(statsColumn)}
	open={statsOpen}
	datasourceConfig={datasource.config as Record<string, unknown>}
	onClose={() => {
		statsOpen = false;
		statsColumn = null;
	}}
/>
