<script lang="ts">
	import type { DataSource } from '$lib/types/datasource';
	import { getDatasourceSchema } from '$lib/api/datasource';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import {
		FileText,
		Database,
		Globe,
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

	interface Props {
		datasource: DataSource | null;
		tabName?: string;
		analysisId?: string;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
	}

	let { datasource, tabName, analysisId, onChangeDatasource, onRenameTab }: Props = $props();

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
		if (!datasource?.id || isLoadingRowCount) return;

		isLoadingRowCount = true;
		getDatasourceSchema(datasource.id).match(
			(schema) => {
				if (schema.row_count !== null && schema.row_count !== undefined) {
					rowCount = schema.row_count;
				}
				isLoadingRowCount = false;
			},
			(error) => {
				console.error('Failed to get row count:', error);
				isLoadingRowCount = false;
			}
		);
	}

	let sourceType = $derived(datasource?.source_type ?? 'file');
	let isDragActive = $derived(drag.active);
</script>

<div class="datasource-node" class:drag-active={isDragActive}>
	<div class="node-content">
		<!-- Header with icon and badge -->
		<div class="node-header">
			<div class="header-left">
				<div class="source-icon">
					{#if sourceType === 'file'}
						<FileText size={14} />
					{:else if sourceType === 'database'}
						<Database size={14} />
					{:else if sourceType === 'api'}
						<Globe size={14} />
					{:else if sourceType === 'iceberg'}
						<Snowflake size={14} />
					{:else}
						<FileText size={14} />
					{/if}
				</div>
				<span class="node-type">source</span>
			</div>
			<span class="node-badge">root</span>
		</div>

		<!-- Tab Section -->
		<div class="info-row">
			<div class="info-label">
				<PanelLeft size={12} />
				<span>Tab name</span>
			</div>
			<div class="info-value">
				{#if isEditing}
					<div class="edit-group">
						<input
							class="tab-name-input"
							bind:value={draftName}
							onkeydown={(e) => {
								if (e.key === 'Enter') commitEdit();
								if (e.key === 'Escape') cancelEdit();
							}}
							aria-label="Edit tab name"
						/>
						<button class="icon-btn save" onclick={commitEdit} type="button" aria-label="Save">
							<Check size={12} />
						</button>
						<button class="icon-btn cancel" onclick={cancelEdit} type="button" aria-label="Cancel">
							<X size={12} />
						</button>
					</div>
				{:else}
					<span class="tab-name">{tabName ?? datasource?.name ?? 'Untitled'}</span>
					{#if onRenameTab}
						<button
							class="icon-btn edit"
							onclick={startEdit}
							type="button"
							aria-label="Edit tab name"
						>
							<Pencil size={12} />
						</button>
					{/if}
				{/if}
			</div>
		</div>

		<!-- Dataset Section -->
		<div class="dataset-section">
			<div class="dataset-header">
				<Database size={12} />
				<span>Dataset</span>
			</div>
			{#if datasource}
				<div class="dataset-card">
					<div class="dataset-info">
						<div class="dataset-name">{datasource.name}</div>
						<div class="dataset-meta">
							{#if datasource.source_type === 'file'}
								<FileTypeBadge
									path={(datasource.config?.file_path as string) ?? ''}
									size="sm"
									showIcon={true}
								/>
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
					<div class="row-count-section">
						{#if rowCount !== null}
							<span class="row-count">
								<Hash size={10} />
								{rowCount.toLocaleString()} rows
							</span>
						{:else}
							<button
								class="calc-rows-btn"
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
				<div class="dataset-empty">
					<span>No datasource connected</span>
				</div>
			{/if}
		</div>

		<!-- Engine Resources Section -->
		{#if analysisId}
			<div class="engine-section">
				<button
					class="engine-header"
					onclick={() => (engineExpanded = !engineExpanded)}
					type="button"
				>
					<div class="engine-header-left">
						<Cpu size={12} />
						<span>Engine</span>
					</div>
					<div class="engine-header-right">
						<span class="engine-summary">
							{effectiveThreads} threads, {effectiveMemoryGb}GB
						</span>
						<span class="chevron" class:expanded={engineExpanded}>
							<ChevronDown size={12} />
						</span>
					</div>
				</button>

				{#if engineExpanded}
					<div class="engine-content">
						<div class="resource-row">
							<label for="threads-input">Threads</label>
							<input
								id="threads-input"
								type="number"
								min="1"
								max="64"
								value={effectiveThreads}
								onchange={(e) => setThreads(parseInt(e.currentTarget.value) || 0)}
							/>
							{#if isUsingDefaultThreads}
								<span class="resource-hint default">(default)</span>
							{/if}
						</div>
						<div class="resource-row">
							<label for="memory-select">Memory</label>
							<select
								id="memory-select"
								value={effectiveMemoryGb}
								onchange={(e) => setMemoryGb(parseInt(e.currentTarget.value) || 0)}
							>
								{#each memoryOptions as gb (gb)}
									<option value={gb}>{gb} GB</option>
								{/each}
							</select>
							{#if isUsingDefaultMemory}
								<span class="resource-hint default">(default)</span>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Action Button -->
		{#if onChangeDatasource}
			<button class="change-source-btn" onclick={onChangeDatasource} type="button">
				<RefreshCw size={14} />
				<span>change source</span>
			</button>
		{/if}
	</div>

	<div class="connection-point"></div>
</div>

<style>
	.datasource-node {
		position: relative;
		width: min(55%, 640px);
	}

	.node-content {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-md);
		padding: var(--space-4);
		transition: all var(--transition);
		box-shadow: var(--shadow-card);
	}
	.node-content:hover {
		border-color: var(--accent-primary);
		box-shadow: var(--shadow-card-hover);
	}

	.node-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-4);
		padding-bottom: var(--space-3);
		border-bottom: 1px solid var(--border-primary);
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.source-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border-radius: var(--radius-sm);
	}

	.node-type {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.node-badge {
		font-size: 10px;
		color: var(--fg-muted);
		background-color: var(--bg-tertiary);
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border: 1px solid var(--border-primary);
	}

	.info-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-secondary);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-3);
		border: 1px solid var(--border-primary);
	}

	.info-label,
	.dataset-header {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--fg-muted);
	}
	.info-label :global(svg),
	.dataset-header :global(svg) {
		opacity: 0.6;
	}

	.info-value {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.tab-name {
		font-size: var(--text-sm);
		font-weight: 500;
	}

	.tab-name-input {
		padding: 2px 8px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--accent-primary);
		background-color: var(--bg-primary);
		font-size: var(--text-sm);
		outline: none;
		min-width: 100px;
	}

	.icon-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		padding: 0;
		border: 1px solid var(--border-secondary);
		background-color: var(--bg-primary);
		color: var(--fg-muted);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition);
		line-height: 1;
	}
	.icon-btn :global(svg) {
		flex-shrink: 0;
	}
	.icon-btn:hover {
		border-color: var(--accent-primary);
		color: var(--fg-primary);
		background-color: var(--bg-tertiary);
	}

	.dataset-section {
		margin-bottom: var(--space-3);
	}
	.dataset-header {
		margin-bottom: var(--space-2);
	}

	.dataset-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-primary);
	}

	.dataset-info {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.dataset-name {
		font-size: var(--text-sm);
		font-weight: 600;
	}
	.dataset-meta {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.row-count-section {
		display: flex;
		align-items: center;
		padding-top: var(--space-2);
		border-top: 1px solid var(--border-primary);
	}

	.row-count {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}

	.calc-rows-btn {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 10px;
		color: var(--fg-muted);
		transition: all var(--transition);
	}
	.calc-rows-btn:hover:not(:disabled) {
		border-color: var(--accent-primary);
		color: var(--fg-primary);
	}
	.calc-rows-btn:disabled {
		cursor: not-allowed;
		opacity: 0.7;
	}

	:global(.spinning) {
		animation: spin 1s linear infinite;
	}

	.dataset-empty {
		padding: var(--space-3);
		border: 1px dashed var(--border-secondary);
		border-radius: var(--radius-sm);
		text-align: center;
	}
	.dataset-empty span {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}

	.change-source-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: 500;
		color: var(--fg-secondary);
		transition: all var(--transition);
	}
	.change-source-btn:hover {
		background-color: var(--bg-tertiary);
		color: var(--fg-primary);
		border-color: var(--accent-primary);
	}
	.change-source-btn :global(svg) {
		opacity: 0.7;
	}
	.change-source-btn:hover :global(svg) {
		opacity: 1;
	}

	.connection-point {
		position: absolute;
		left: 50%;
		bottom: -5px;
		transform: translateX(-50%);
		width: 10px;
		height: 10px;
		background-color: var(--bg-primary);
		border: 2px solid var(--accent-primary);
		border-radius: 50%;
		z-index: 2;
	}

	.edit-group {
		display: flex;
		align-items: center;
		gap: var(--space-1);
	}
	.icon-btn.edit {
		opacity: 0.5;
	}
	.icon-btn.edit:hover {
		opacity: 1;
	}
	.icon-btn.save {
		border-color: var(--success-border);
		color: var(--success-fg);
	}
	.icon-btn.save:hover {
		background-color: var(--success-bg);
	}
	.icon-btn.cancel {
		border-color: var(--error-border);
		color: var(--error-fg);
	}
	.icon-btn.cancel:hover {
		background-color: var(--error-bg);
	}

	.datasource-node.drag-active .node-content {
		border-color: var(--accent-primary);
		border-style: dashed;
		opacity: 0.85;
	}

	/* Engine Resources Section */
	.engine-section {
		margin-bottom: var(--space-3);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.engine-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-secondary);
		border: none;
		cursor: pointer;
		transition: all var(--transition);
	}
	.engine-header:hover {
		background-color: var(--bg-tertiary);
	}

	.engine-header-left {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--fg-muted);
	}

	.engine-header-right {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.engine-summary {
		font-size: 10px;
		color: var(--fg-secondary);
		font-family: var(--font-mono);
	}

	.engine-header .chevron {
		display: flex;
		align-items: center;
		color: var(--fg-muted);
		transition: transform var(--transition);
	}
	.engine-header .chevron.expanded {
		transform: rotate(180deg);
	}

	.engine-content {
		padding: var(--space-3);
		background-color: var(--bg-primary);
		border-top: 1px solid var(--border-primary);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.resource-row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.resource-row label {
		font-size: var(--text-xs);
		color: var(--fg-secondary);
		min-width: 60px;
	}

	.resource-row input,
	.resource-row select {
		flex: 1;
		padding: var(--space-1) var(--space-2);
		background-color: var(--bg-secondary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		color: var(--fg-primary);
	}

	.resource-row input:focus,
	.resource-row select:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.resource-hint {
		font-size: 9px;
		color: var(--fg-muted);
		min-width: 50px;
	}

	.resource-hint.default {
		color: var(--fg-tertiary);
		font-style: italic;
	}
</style>
