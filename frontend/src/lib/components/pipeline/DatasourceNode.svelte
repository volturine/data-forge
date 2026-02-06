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

<div class="datasource-node relative w-[65%]" class:drag-active={isDragActive}>
	<div
		class="node-content rounded-md border p-4 transition-all"
		style="background-color: var(--bg-primary); border-color: var(--border-secondary); box-shadow: var(--shadow-card);"
	>
		<!-- Header with icon and badge -->
		<div
			class="mb-4 flex items-center justify-between border-b pb-3"
			style="border-color: var(--border-primary);"
		>
			<div class="flex items-center gap-2">
				<div
					class="flex h-6 w-6 items-center justify-center rounded-sm"
					style="background-color: var(--accent-primary); color: var(--bg-primary);"
				>
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
				<span class="text-sm font-semibold">source</span>
			</div>
			<span
				class="rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
				style="color: var(--fg-muted); background-color: var(--bg-tertiary); border-color: var(--border-primary);"
			>root</span>
		</div>

		<!-- Tab Section -->
		<div
			class="mb-3 flex items-center justify-between rounded-sm border p-2 px-3"
			style="background-color: var(--bg-secondary); border-color: var(--border-primary);"
		>
			<div class="info-label flex items-center gap-2 text-xs uppercase tracking-wide" style="color: var(--fg-muted);">
				<PanelLeft size={12} class="opacity-60" />
				<span>Tab name</span>
			</div>
			<div class="flex items-center gap-2">
				{#if isEditing}
					<div class="flex items-center gap-1">
						<input
							class="min-w-[100px] rounded-sm border px-2 py-0.5 text-sm outline-none"
							style="border-color: var(--accent-primary); background-color: var(--bg-primary);"
							bind:value={draftName}
							onkeydown={(e) => {
								if (e.key === 'Enter') commitEdit();
								if (e.key === 'Escape') cancelEdit();
							}}
							aria-label="Edit tab name"
						/>
						<button
							class="icon-btn save inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-sm border p-0 leading-none transition-all"
							onclick={commitEdit}
							type="button"
							aria-label="Save"
							style="border-color: var(--success-border); color: var(--success-fg); background-color: var(--bg-primary);"
						>
							<Check size={12} class="shrink-0" />
						</button>
						<button
							class="icon-btn cancel inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-sm border p-0 leading-none transition-all"
							onclick={cancelEdit}
							type="button"
							aria-label="Cancel"
							style="border-color: var(--error-border); color: var(--error-fg); background-color: var(--bg-primary);"
						>
							<X size={12} class="shrink-0" />
						</button>
					</div>
				{:else}
					<span class="text-sm font-medium">{tabName ?? datasource?.name ?? 'Untitled'}</span>
					{#if onRenameTab}
						<button
							class="icon-btn edit inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-sm border p-0 opacity-50 leading-none transition-all"
							onclick={startEdit}
							type="button"
							aria-label="Edit tab name"
							style="border-color: var(--border-secondary); color: var(--fg-muted); background-color: var(--bg-primary);"
						>
							<Pencil size={12} class="shrink-0" />
						</button>
					{/if}
				{/if}
			</div>
		</div>

		<!-- Dataset Section -->
		<div class="mb-3">
			<div class="info-label mb-2 flex items-center gap-2 text-xs uppercase tracking-wide" style="color: var(--fg-muted);">
				<Database size={12} class="opacity-60" />
				<span>Dataset</span>
			</div>
			{#if datasource}
				<div
					class="flex flex-col gap-2 rounded-sm border p-3"
					style="background-color: var(--bg-tertiary); border-color: var(--border-primary);"
				>
					<div class="flex items-center justify-between">
						<div class="text-sm font-semibold">{datasource.name}</div>
						<div class="flex items-center gap-2">
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
					<div class="flex items-center border-t pt-2" style="border-color: var(--border-primary);">
						{#if rowCount !== null}
							<span class="flex items-center gap-1 text-xs" style="color: var(--fg-muted);">
								<Hash size={10} />
								{rowCount.toLocaleString()} rows
							</span>
						{:else}
							<button
								class="calc-rows-btn flex cursor-pointer items-center gap-1 rounded-sm border px-2 py-0.5 text-[10px] transition-all disabled:cursor-not-allowed disabled:opacity-70"
								onclick={calculateRowCount}
								disabled={isLoadingRowCount}
								type="button"
								aria-label="Calculate row count"
								style="background-color: var(--bg-secondary); border-color: var(--border-secondary); color: var(--fg-muted);"
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
				<div
					class="rounded-sm border border-dashed p-3 text-center"
					style="border-color: var(--border-secondary);"
				>
					<span class="text-xs" style="color: var(--fg-muted);">No datasource connected</span>
				</div>
			{/if}
		</div>

		<!-- Engine Resources Section -->
		{#if analysisId}
			<div class="mb-3 overflow-hidden rounded-sm border" style="border-color: var(--border-primary);">
				<button
					class="engine-header flex w-full cursor-pointer items-center justify-between border-none p-2 px-3 transition-all"
					onclick={() => (engineExpanded = !engineExpanded)}
					type="button"
					style="background-color: var(--bg-secondary);"
				>
					<div class="flex items-center gap-2 text-xs uppercase tracking-wide" style="color: var(--fg-muted);">
						<Cpu size={12} />
						<span>Engine</span>
					</div>
					<div class="flex items-center gap-2">
						<span class="font-mono text-[10px]" style="color: var(--fg-secondary);">
							{effectiveThreads} threads, {effectiveMemoryGb}GB
						</span>
						<span
							class="chevron flex items-center transition-transform"
							class:expanded={engineExpanded}
							style="color: var(--fg-muted);"
						>
							<ChevronDown size={12} />
						</span>
					</div>
				</button>

				{#if engineExpanded}
					<div
						class="flex flex-col gap-2 border-t p-3"
						style="background-color: var(--bg-primary); border-color: var(--border-primary);"
					>
						<div class="flex items-center gap-3">
							<label for="threads-input" class="min-w-[60px] text-xs" style="color: var(--fg-secondary);">Threads</label>
							<input
								id="threads-input"
								class="resource-input flex-1 rounded-sm border p-1 px-2 font-mono text-xs"
								type="number"
								min="1"
								max="64"
								value={effectiveThreads}
								onchange={(e) => setThreads(parseInt(e.currentTarget.value) || 0)}
								style="background-color: var(--bg-secondary); border-color: var(--border-primary); color: var(--fg-primary);"
							/>
							{#if isUsingDefaultThreads}
								<span class="min-w-[50px] text-[9px] italic" style="color: var(--fg-tertiary);">(default)</span>
							{/if}
						</div>
						<div class="flex items-center gap-3">
							<label for="memory-select" class="min-w-[60px] text-xs" style="color: var(--fg-secondary);">Memory</label>
							<select
								id="memory-select"
								class="resource-input flex-1 rounded-sm border p-1 px-2 font-mono text-xs"
								value={effectiveMemoryGb}
								onchange={(e) => setMemoryGb(parseInt(e.currentTarget.value) || 0)}
								style="background-color: var(--bg-secondary); border-color: var(--border-primary); color: var(--fg-primary);"
							>
								{#each memoryOptions as gb (gb)}
									<option value={gb}>{gb} GB</option>
								{/each}
							</select>
							{#if isUsingDefaultMemory}
								<span class="min-w-[50px] text-[9px] italic" style="color: var(--fg-tertiary);">(default)</span>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Action Button -->
		{#if onChangeDatasource}
			<button
				class="change-source-btn flex w-full cursor-pointer items-center justify-center gap-2 rounded-sm border p-2 px-3 text-xs font-medium transition-all"
				onclick={onChangeDatasource}
				type="button"
				style="background-color: var(--bg-secondary); border-color: var(--border-primary); color: var(--fg-secondary);"
			>
				<RefreshCw size={14} class="opacity-70" />
				<span>change source</span>
			</button>
		{/if}
	</div>

	<div
		class="absolute bottom-[-5px] left-1/2 z-[2] h-2.5 w-2.5 -translate-x-1/2 rounded-full"
		style="background-color: var(--bg-primary); border: 2px solid var(--accent-primary);"
	></div>
</div>

<style>
	.node-content:hover {
		border-color: var(--accent-primary);
		box-shadow: var(--shadow-card-hover);
	}

	.icon-btn:hover {
		border-color: var(--accent-primary);
		color: var(--fg-primary);
		background-color: var(--bg-tertiary);
	}

	.icon-btn.edit:hover {
		opacity: 1;
	}

	.icon-btn.save:hover {
		background-color: var(--success-bg);
	}

	.icon-btn.cancel:hover {
		background-color: var(--error-bg);
	}

	.calc-rows-btn:hover:not(:disabled) {
		border-color: var(--accent-primary);
		color: var(--fg-primary);
	}

	:global(.spinning) {
		animation: spin 1s linear infinite;
	}

	.change-source-btn:hover {
		background-color: var(--bg-tertiary);
		color: var(--fg-primary);
		border-color: var(--accent-primary);
	}

	.change-source-btn:hover :global(svg) {
		opacity: 1;
	}

	.engine-header:hover {
		background-color: var(--bg-tertiary);
	}

	.chevron.expanded {
		transform: rotate(180deg);
	}

	.resource-input:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.datasource-node.drag-active .node-content {
		border-color: var(--accent-primary);
		border-style: dashed;
		opacity: 0.85;
	}
</style>
