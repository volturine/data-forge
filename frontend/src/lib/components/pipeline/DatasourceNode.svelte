<script lang="ts">
	import type { DataSource } from '$lib/types/datasource';
	import type { AnalysisTab } from '$lib/types/analysis';
	import { getDatasourceSchema } from '$lib/api/datasource';
	interface AnalysisExecuteResponse {
		schema: Record<string, string>;
		rows: Array<Record<string, unknown>>;
		row_count?: number;
	}
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { track } from '$lib/utils/audit-log';
	import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
	import {
		FileText,
		Database,
		Globe,
		Layers,
		Snowflake,
		PanelLeft,
		Pencil,
		RefreshCw,
		Hash,
		Check,
		X,
		Cpu,
		ChevronDown
	} from 'lucide-svelte';
	import { drag } from '$lib/stores/drag.svelte';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import SnapshotPicker from '$lib/components/datasources/SnapshotPicker.svelte';
	import type { SourceType } from '$lib/utils/fileTypes';

	interface Props {
		datasource: DataSource | null;
		tabName?: string;
		analysisId?: string;
		activeTab?: AnalysisTab | null;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
	}

	let { datasource, tabName, analysisId, activeTab, onChangeDatasource, onRenameTab }: Props =
		$props();

	let isEditing = $state(false);
	let draftName = $state('');
	let rowCount = $state<number | null>(null);
	let isLoadingRowCount = $state(false);

	// Engine config - simple state bound to store
	let engineExpanded = $state(false);

	// Use defaults from store (fetched by analysis page on load)
	let defaults = $derived(analysisStore.engineDefaults);

	// Threads: show effective value (default when not overridden)
	let threadsOverride = $derived(analysisStore.resourceConfig?.max_threads ?? 0);
	let effectiveThreads = $derived(threadsOverride || defaults?.max_threads || 0);
	let isUsingDefaultThreads = $derived(threadsOverride === 0);
	function setThreads(value: number) {
		const current = analysisStore.resourceConfig ?? {};
		// If set to the default value, treat as "use default" (store undefined)
		const defaultThreads = defaults?.max_threads ?? 0;
		const storeValue = value === defaultThreads ? undefined : value || undefined;
		analysisStore.setResourceConfig({ ...current, max_threads: storeValue });
	}

	// Memory: show effective value (default when not overridden)
	let memoryGbOverride = $derived(
		Math.floor((analysisStore.resourceConfig?.max_memory_mb ?? 0) / 1024)
	);
	let effectiveMemoryGb = $derived(
		memoryGbOverride || Math.floor((defaults?.max_memory_mb ?? 0) / 1024)
	);
	let isUsingDefaultMemory = $derived(memoryGbOverride === 0);
	function setMemoryGb(value: number) {
		const current = analysisStore.resourceConfig ?? {};
		// If set to the default value, treat as "use default" (store undefined)
		const defaultMemoryGb = Math.floor((defaults?.max_memory_mb ?? 0) / 1024);
		const storeValue = value === defaultMemoryGb ? undefined : value ? value * 1024 : undefined;
		analysisStore.setResourceConfig({ ...current, max_memory_mb: storeValue });
	}

	const standardMemoryOptions = [1, 2, 4, 8, 16, 32, 64];
	// Include the default/effective value in options if not already present
	let memoryOptions = $derived.by(() => {
		const val = effectiveMemoryGb;
		if (val && !standardMemoryOptions.includes(val)) {
			return [...standardMemoryOptions, val].sort((a, b) => a - b);
		}
		return standardMemoryOptions;
	});

	$effect(() => {
		if (!isEditing) {
			draftName = tabName ?? datasource?.name ?? '';
		}
	});

	// Reset row count when datasource changes
	$effect(() => {
		if (datasource?.id) {
			rowCount = null;
		}
	});

	const isIceberg = $derived(datasource?.source_type === 'iceberg');
	function updateTimeTravelUi(updates: { open?: boolean; month?: string; day?: string }) {
		const active = activeTab;
		if (!active) return;
		const nextConfig = { ...(active.datasource_config ?? {}) };
		const currentUi = (nextConfig.time_travel_ui as Record<string, unknown>) ?? {};
		nextConfig.time_travel_ui = { ...currentUi, ...updates };
		analysisStore.updateTab(active.id, { datasource_config: nextConfig });
	}

	function updateSnapshotConfig(nextConfig: Record<string, unknown>) {
		const active = activeTab;
		if (!active) return;
		analysisStore.updateTab(active.id, { datasource_config: nextConfig });
		analysisStore.setActiveTab(active.id);
	}

	function handleSnapshotSelect(snapshotId: string | null, timestampMs?: number) {
		schemaStore.reset();
		track({
			event: 'analysis_time_travel',
			action: snapshotId ? 'set_snapshot' : 'set_latest',
			target: datasource?.id ?? '',
			meta: {
				snapshot_id: snapshotId,
				snapshot_timestamp_ms: timestampMs
			}
		});
	}

	function startEdit() {
		if (!onRenameTab) return;
		isEditing = true;
		draftName = tabName ?? datasource?.name ?? '';
	}

	function cancelEdit() {
		isEditing = false;
		draftName = tabName ?? datasource?.name ?? '';
	}

	function commitEdit() {
		if (!onRenameTab) {
			cancelEdit();
			return;
		}
		const next = draftName.trim();
		if (!next) {
			cancelEdit();
			return;
		}
		onRenameTab(next);
		isEditing = false;
	}

	async function calculateRowCount() {
		if (isLoadingRowCount) return;
		if (analysisSourceId) {
			const analysisPayload =
				analysisId && analysisSourceId === analysisId
					? buildAnalysisPipelinePayload(
							analysisId,
							analysisStore.tabs,
							datasourceStore.datasources
						)
					: null;
			const tabParam = analysisSourceTabId
				? `?analysis_tab_id=${encodeURIComponent(analysisSourceTabId)}`
				: '';
			const body = analysisPayload ? JSON.stringify({ pipeline: analysisPayload }) : undefined;
			isLoadingRowCount = true;
			await fetch(`/api/v1/analysis/${analysisSourceId}/execute${tabParam}`, {
				method: 'POST',
				body,
				headers: body ? { 'Content-Type': 'application/json' } : undefined
			})
				.then((response) => {
					if (!response.ok) {
						throw new Error('Failed to execute analysis');
					}
					return response.json() as Promise<AnalysisExecuteResponse>;
				})
				.then((payload) => {
					rowCount = payload.row_count ?? payload.rows.length;
					isLoadingRowCount = false;
				})
				.catch((error: unknown) => {
					const message = error instanceof Error ? error.message : 'Failed to execute analysis';
					track({
						event: 'schema_error',
						action: 'analysis_source_row_count',
						target: analysisSourceId,
						meta: { message }
					});
					isLoadingRowCount = false;
				});
			return;
		}

		if (!datasource?.id) return;
		isLoadingRowCount = true;
		getDatasourceSchema(datasource.id).match(
			(schema) => {
				if (schema.row_count !== null && schema.row_count !== undefined) {
					rowCount = schema.row_count;
				}
				isLoadingRowCount = false;
			},
			(error) => {
				track({
					event: 'schema_error',
					action: 'row_count',
					target: datasource.id,
					meta: { message: error.message }
				});
				isLoadingRowCount = false;
			}
		);
	}

	let analysisSourceId = $derived(
		(activeTab?.datasource_config?.analysis_id as string | null) ??
			(datasource?.config?.analysis_id as string | null) ??
			null
	);
	let analysisSourceTabId = $derived(
		(activeTab?.datasource_config?.analysis_tab_id as string | null) ??
			(datasource?.config?.analysis_tab_id as string | null) ??
			null
	);
	let sourceType = $derived(
		(analysisSourceId ? 'analysis' : (datasource?.source_type ?? 'file')) as string
	);
	let isDragActive = $derived(drag.active);
</script>

<div class="datasource-node relative w-[65%]" class:drag-active={isDragActive}>
	<div class="node-content bg-primary border-tertiary border p-4 hover:border-tertiary">
		<!-- Header with icon and badge -->
		<div class="mb-4 flex items-center justify-between border-b border-tertiary pb-3">
			<div class="flex items-center gap-2">
				<div class="flex h-6 w-6 items-center justify-center bg-accent text-bg-primary">
					{#if sourceType === 'file'}
						<FileText size={14} />
					{:else if sourceType === 'database'}
						<Database size={14} />
					{:else if sourceType === 'api'}
						<Globe size={14} />
					{:else if sourceType === 'iceberg'}
						<Snowflake size={14} />
					{:else if sourceType === 'analysis'}
						<Layers size={14} />
					{:else}
						<FileText size={14} />
					{/if}
				</div>
				<span class="text-sm font-semibold">source</span>
			</div>
			<span
				class="rounded-sm border border-tertiary bg-tertiary text-fg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
				>root</span
			>
		</div>

		<!-- Tab Section -->
		<div
			class="mb-3 flex items-center justify-between border border-tertiary bg-secondary p-2 px-3"
		>
			<div class="info-label flex items-center gap-2 text-xs uppercase tracking-wide text-fg-muted">
				<PanelLeft size={12} class="opacity-60" />
				<span>Tab name</span>
			</div>
			<div class="flex items-center gap-2">
				{#if isEditing}
					<div class="flex items-center gap-1">
						<input
							class="min-w-25 border border-tertiary bg-primary px-2 py-0.5 text-sm outline-none"
							bind:value={draftName}
							onkeydown={(e) => {
								if (e.key === 'Enter') commitEdit();
								if (e.key === 'Escape') cancelEdit();
							}}
							aria-label="Edit tab name"
						/>
						<button
							class="icon-btn save inline-flex h-5 w-5 cursor-pointer items-center justify-center border border-accent-primary text-success bg-primary p-0 leading-none hover:bg-success hover:text-fg-primary"
							onclick={commitEdit}
							type="button"
							aria-label="Save"
						>
							<Check size={12} class="shrink-0" />
						</button>
						<button
							class="icon-btn cancel inline-flex h-5 w-5 cursor-pointer items-center justify-center border border-error text-error bg-primary p-0 leading-none hover:bg-error hover:text-fg-primary"
							onclick={cancelEdit}
							type="button"
							aria-label="Cancel"
						>
							<X size={12} class="shrink-0" />
						</button>
					</div>
				{:else}
					<span class="text-sm font-medium">{tabName ?? datasource?.name ?? 'Untitled'}</span>
					{#if onRenameTab}
						<button
							class="icon-btn edit inline-flex h-5 w-5 cursor-pointer items-center justify-center border border-tertiary text-fg-muted bg-primary p-0 opacity-50 leading-none hover:border-tertiary hover:text-fg-primary hover:bg-tertiary hover:opacity-100"
							onclick={startEdit}
							type="button"
							aria-label="Edit tab name"
						>
							<Pencil size={12} class="shrink-0" />
						</button>
					{/if}
				{/if}
			</div>
		</div>

		<!-- Dataset Section -->
		<div class="mb-3">
			<div
				class="info-label mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-fg-muted"
			>
				<Database size={12} class="opacity-60" />
				<span>Dataset</span>
			</div>
			{#if datasource}
				<div class="flex flex-col gap-2 border border-tertiary bg-tertiary p-3">
					<div class="flex items-center justify-between">
						<div class="text-sm font-semibold">{datasource.name}</div>
						<div class="flex items-center gap-2">
							{#if datasource.source_type === 'file'}
								<FileTypeBadge
									path={(datasource.config?.file_path as string) ?? ''}
									size="sm"
									showIcon={true}
								/>
							{:else if datasource.source_type === 'analysis'}
								{@const badgeSource = sourceType as SourceType}
								<FileTypeBadge sourceType={badgeSource} size="sm" showIcon={true} />
							{:else}
								<FileTypeBadge
									sourceType={datasource.source_type as 'database' | 'api' | 'iceberg' | 'duckdb'}
									size="sm"
									showIcon={true}
								/>
							{/if}
						</div>
					</div>
					<!-- Row count section -->
					<div class="flex items-center border-t border-tertiary pt-2">
						{#if rowCount !== null}
							<span class="flex items-center gap-1 text-xs text-fg-muted">
								<Hash size={10} />
								{rowCount.toLocaleString()} rows
							</span>
						{:else}
							<button
								class="calc-rows-btn flex cursor-pointer items-center gap-1 border border-tertiary bg-secondary text-fg-muted px-2 py-0.5 text-[10px] disabled:cursor-not-allowed disabled:opacity-70 hover:border-tertiary hover:text-fg-primary"
								onclick={calculateRowCount}
								disabled={isLoadingRowCount}
								type="button"
								aria-label="Calculate row count"
							>
								{#if isLoadingRowCount}
									<RefreshCw size={10} class="spinning" />
									<span>counting...</span>
								{:else}
									<Hash size={10} />
									<span>count rows</span>
								{/if}
							</button>
						{/if}
					</div>
				</div>
			{:else}
				<div class="rounded-sm border border-dashed border-tertiary p-3 text-center">
					<span class="text-xs text-fg-muted">No datasource connected</span>
				</div>
			{/if}
		</div>

		<!-- Engine Resources Section -->
		{#if analysisId}
			<div class="mb-3 overflow-hidden border border-tertiary">
				<button
					class="engine-header flex w-full cursor-pointer items-center justify-between border-none bg-secondary p-2 px-3 hover:bg-tertiary"
					onclick={() => (engineExpanded = !engineExpanded)}
					type="button"
				>
					<div class="flex items-center gap-2 text-xs uppercase tracking-wide text-fg-muted">
						<Cpu size={12} />
						<span>Engine</span>
					</div>
					<div class="flex items-center gap-2">
						<span class="font-mono text-[10px] text-fg-secondary">
							{effectiveThreads} threads, {effectiveMemoryGb}GB
						</span>
						<span class="chevron flex items-center text-fg-muted" class:expanded={engineExpanded}>
							<ChevronDown size={12} />
						</span>
					</div>
				</button>

				{#if engineExpanded}
					<div class="flex flex-col gap-2 border-t border-tertiary bg-primary p-3">
						<div class="flex items-center gap-3">
							<label for="threads-input" class="min-w-15 text-xs text-fg-secondary">Threads</label>
							<input
								id="threads-input"
								class="resource-input flex-1 border border-tertiary bg-secondary text-fg-primary p-1 px-2 font-mono text-xs focus:border-accent-primary focus:outline-none"
								type="number"
								min="1"
								max="64"
								value={effectiveThreads}
								onchange={(e) => setThreads(parseInt(e.currentTarget.value) || 0)}
							/>
							{#if isUsingDefaultThreads}
								<span class="min-w-12.5 text-[9px] italic text-fg-tertiary">(default)</span>
							{/if}
						</div>
						<div class="flex items-center gap-3">
							<label for="memory-select" class="min-w-15 text-xs text-fg-secondary">Memory</label>
							<select
								id="memory-select"
								class="resource-input flex-1 border border-tertiary bg-secondary text-fg-primary p-1 px-2 font-mono text-xs focus:border-accent-primary focus:outline-none"
								value={effectiveMemoryGb}
								onchange={(e) => setMemoryGb(parseInt(e.currentTarget.value) || 0)}
							>
								{#each memoryOptions as gb (gb)}
									<option value={gb}>{gb} GB</option>
								{/each}
							</select>
							{#if isUsingDefaultMemory}
								<span class="min-w-12.5 text-[9px] italic text-fg-tertiary">(default)</span>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		{#if isIceberg && datasource}
			<div class="mb-3">
				<SnapshotPicker
					datasourceId={datasource.id}
					datasourceConfig={activeTab?.datasource_config ?? {}}
					label="Time Travel"
					persistOpen
					onConfigChange={updateSnapshotConfig}
					onUiChange={updateTimeTravelUi}
					onSelect={handleSnapshotSelect}
				/>
			</div>
		{/if}

		<!-- Action Button -->
		{#if onChangeDatasource}
			<button
				class="change-source-btn flex w-full cursor-pointer items-center justify-center gap-2 border border-tertiary bg-secondary text-fg-secondary p-2 px-3 text-xs font-medium hover:bg-tertiary hover:text-fg-primary hover:border-accent-primary [&:hover_svg]:opacity-100"
				onclick={onChangeDatasource}
				type="button"
			>
				<RefreshCw size={14} class="opacity-70" />
				<span>change source</span>
			</button>
		{/if}
	</div>

	<div
		class="absolute -bottom-1.25 left-1/2 z-2 h-2.5 w-2.5 -translate-x-1/2 bg-primary border-2 border-accent-primary"
	></div>
</div>
