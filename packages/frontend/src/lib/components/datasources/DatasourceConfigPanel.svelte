<script lang="ts">
	import { untrack } from 'svelte';
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import {
		getDatasource,
		getDatasourceSchema,
		ingestDatasource,
		updateDatasource,
		updateDatasourceColumnDescriptions
	} from '$lib/api/datasource';
	import { BuildsStore } from '$lib/stores/builds.svelte';
	import { CircleAlert } from '@lucide/svelte';
	import type { DataSource, SchemaInfo, ColumnSchema } from '$lib/types/datasource';
	import {
		datasourceFileConfig,
		datasourceIsAnalysisOutput,
		datasourceIsCsv,
		datasourceIsExcel,
		datasourceIsFile,
		datasourceIsIceberg,
		datasourceIsSchedulableRaw,
		datasourceNeedsExternalIngest,
		datasourceSupportsSchemaRefresh
	} from '$lib/types/datasource';
	import type { FileDataSource, IcebergDataSource } from '$lib/types/datasource';
	import ColumnStatsPanel from '$lib/components/datasources/ColumnStatsPanel.svelte';
	import HealthChecksManager from '$lib/components/common/HealthChecksManager.svelte';
	import ScheduleManager from '$lib/components/common/ScheduleManager.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import DatasourceGeneralTab, { FRESHNESS_THRESHOLD_OPTIONS } from './DatasourceGeneralTab.svelte';
	import DatasourceSchemaTab from './DatasourceSchemaTab.svelte';
	import DatasourceCsvOptionsTab, { type CsvConfig } from './DatasourceCsvOptionsTab.svelte';
	import DatasourceExcelOptionsTab, { type ExcelConfig } from './DatasourceExcelOptionsTab.svelte';
	import DatasourceRunsTab from './DatasourceRunsTab.svelte';
	import { resolveColumnType } from '$lib/utils/column-types';
	import { css, tabButton } from '$lib/styles/panda';
	import { useNamespace } from '$lib/stores/namespace.svelte';

	interface Props {
		datasource: DataSource;
		onSave?: () => void;
	}

	let { datasource, onSave }: Props = $props();

	const queryClient = useQueryClient();
	const ns = useNamespace();

	const datasourceQuery = createQuery(() => ({
		queryKey: ['datasource', ns.value, datasource.id],
		queryFn: async () => {
			const result = await getDatasource(datasource.id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		initialData: datasource,
		refetchOnMount: false
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

	const buildRunsStore = new BuildsStore();
	let runsRequested = false;

	// Network: keep run history dormant until the user opens the Runs tab.
	$effect(() => {
		if (activeTab !== 'runs' || !datasource.id) return;
		if (!untrack(() => runsRequested)) {
			buildRunsStore.load({ datasource_id: datasource.id, limit: 50 });
			runsRequested = true;
			return;
		}
		buildRunsStore.silentRefresh();
	});

	// Subscription: keep any in-flight runs requests alive during normal tab switches.
	$effect(() => {
		return () => {
			buildRunsStore.close();
		};
	});

	const updateMutation = createMutation(() => ({
		mutationFn: async (update: {
			name: string;
			description: string | null;
			config?: Record<string, unknown>;
			freshness_threshold_minutes?: number | null;
		}) => {
			const result = await updateDatasource(datasource.id, update);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['datasource', ns.value, datasource.id] });
			queryClient.invalidateQueries({ queryKey: ['datasource-schema', datasource.id] });
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
			onSave?.();
		}
	}));

	let name = $state('');
	let description = $state('');
	let columns = $state.raw<ColumnSchema[]>([]);
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
	let freshnessThreshold = $state<number | null>(null);
	let customFreshnessThreshold = $state('');
	let isCustomFreshnessThreshold = $state(false);

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
		buildRunsStore.reset();
		runsRequested = false;

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
		freshnessThreshold = ds.freshness_threshold_minutes ?? null;
		isCustomFreshnessThreshold =
			ds.freshness_threshold_minutes != null &&
			!FRESHNESS_THRESHOLD_OPTIONS.some(
				(option) => option.minutes === ds.freshness_threshold_minutes
			);
		customFreshnessThreshold = isCustomFreshnessThreshold
			? String(ds.freshness_threshold_minutes)
			: '';

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
	let csvConfig = $state<CsvConfig>({
		delimiter: ',',
		quote_char: '"',
		has_header: true,
		skip_rows: 0,
		encoding: 'utf8'
	});

	// Excel-specific state
	let excelConfig = $state<ExcelConfig>({
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

	function getFileSource(ds: DataSource) {
		return datasourceFileConfig(ds);
	}

	function isCsv(ds: DataSource): boolean {
		return datasourceIsCsv(ds);
	}

	function isExcel(ds: DataSource): boolean {
		return datasourceIsExcel(ds);
	}

	function isFile(ds: DataSource): ds is FileDataSource {
		return datasourceIsFile(ds);
	}

	function isIceberg(ds: DataSource): ds is IcebergDataSource {
		return datasourceIsIceberg(ds);
	}

	function markDirty() {
		hasChanges = true;
		configDirty = true;
	}

	async function handleSave() {
		if (!datasourceQuery.data) return;

		const update: {
			name: string;
			description: string | null;
			config?: Record<string, unknown>;
			freshness_threshold_minutes?: number | null;
		} = {
			name,
			description,
			freshness_threshold_minutes: freshnessThreshold
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
				if (isIceberg(datasourceQuery.data)) {
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
				if (isIceberg(datasourceQuery.data)) {
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

		if (update.config && datasourceNeedsExternalIngest(ds)) {
			const ingestResult = await ingestDatasource(ds.id);
			if (ingestResult.isErr()) {
				refreshError = ingestResult.error.message || 'Failed to re-ingest datasource';
				return;
			}
			queryClient.invalidateQueries({ queryKey: ['datasource', ns.value, ds.id] });
			queryClient.invalidateQueries({ queryKey: ['datasource-schema', ds.id] });
			queryClient.invalidateQueries({ queryKey: ['datasource-preview', ds.id] });
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
		}
	}

	async function handleIngest() {
		refreshError = null;
		isRefreshing = true;
		const previousColumns = new Map(columns.map((col) => [col.name, col.dtype]));

		if (!datasourceSupportsSchemaRefresh(datasource)) {
			refreshError = 'Schema refresh is unavailable for analysis datasources';
			isRefreshing = false;
			return;
		}
		try {
			const reingested = datasourceNeedsExternalIngest(datasource);
			if (reingested) {
				const ingestResult = await ingestDatasource(datasource.id);
				if (ingestResult.isErr()) {
					throw new Error(ingestResult.error.message);
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
			refreshError = error instanceof Error ? error.message : 'Failed to ingest datasource schema';
		} finally {
			isRefreshing = false;
		}
	}

	function openColumnStats(columnName: string) {
		statsColumn = columnName;
		statsOpen = true;
	}

	const ds = $derived(datasourceQuery.data ?? datasource);
	const csv = $derived(isCsv(ds));
	const excel = $derived(isExcel(ds));
	const isOutputDatasource = $derived(datasourceIsAnalysisOutput(ds));
	const scheduleAnalysisId = $derived(
		isOutputDatasource
			? (ds.created_by_analysis_id ?? (ds.config?.analysis_id as string | undefined) ?? null)
			: null
	);
	const rawSchedulable = $derived(datasourceIsSchedulableRaw(ds));
	const refreshActionLabel = $derived(
		datasourceNeedsExternalIngest(ds) ? 'Re-ingest from source' : 'Refresh schema'
	);
	const refreshBusyLabel = $derived(
		datasourceNeedsExternalIngest(ds) ? 'Re-ingesting...' : 'Refreshing schema...'
	);

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
		</button>
		<button
			class={tabButton({ active: activeTab === 'health' })}
			onclick={() => (activeTab = 'health')}
			role="tab"
			aria-selected={activeTab === 'health'}
		>
			Health Checks
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
			<DatasourceGeneralTab
				datasourceId={datasource.id}
				{ds}
				schema={schemaQuery.data}
				bind:name
				bind:description
				bind:freshnessThreshold
				bind:customFreshnessThreshold
				bind:isCustomFreshnessThreshold
				savePending={updateMutation.isPending}
				{hasChanges}
				{isRefreshing}
				{refreshActionLabel}
				{refreshBusyLabel}
				onDirty={() => (hasChanges = true)}
				onIngest={handleIngest}
				onSave={handleSave}
			/>
		{:else if activeTab === 'schema'}
			<DatasourceSchemaTab
				{columns}
				loading={schemaQuery.isLoading}
				{refreshError}
				{schemaChanged}
				{schemaDiff}
				descriptionPending={descriptionMutation.isPending}
				bind:descriptionDraft
				{descriptionError}
				{editingColumn}
				{isDescriptionExpanded}
				onSelectColumn={openColumnStats}
				onToggleDescription={toggleDescription}
				onStartEdit={startEditingDescription}
				onCancelEdit={cancelEditingDescription}
				onSaveDescription={saveDescription}
			/>
		{:else if activeTab === 'csv' && csv}
			<DatasourceCsvOptionsTab
				datasourceId={datasource.id}
				bind:config={csvConfig}
				pending={updateMutation.isPending}
				{hasChanges}
				onDirty={markDirty}
				onSave={handleSave}
			/>
		{:else if activeTab === 'excel' && excel}
			<DatasourceExcelOptionsTab
				filePath={getFileSource(ds)?.file_path ?? null}
				bind:config={excelConfig}
				pending={updateMutation.isPending}
				{hasChanges}
				onDirty={markDirty}
				onSave={handleSave}
			/>
		{:else if activeTab === 'runs'}
			<DatasourceRunsTab
				datasourceId={datasource.id}
				builds={buildRunsStore.builds}
				status={buildRunsStore.status}
				error={buildRunsStore.error}
				{showPreviews}
				onTogglePreviews={() => (showPreviews = !showPreviews)}
			/>
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
