<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';

	interface UnionByNameConfigData {
		sources: string[];
		allow_missing: boolean;
	}

	const defaultConfig: UnionByNameConfigData = {
		sources: [],
		allow_missing: true
	};

	interface Props {
		schema: Schema;
		config?: UnionByNameConfigData;
	}

	let { schema, config = $bindable(defaultConfig) }: Props = $props();

	let selectedSources = $state<string[]>(config.sources ?? []);
	let loadedSources = $state<string[]>([]);
	let search = $state('');
	let showPicker = $state(false);

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource_id ?? null);
	const currentDatasource = $derived(
		datasourceStore.datasources.find((ds) => ds.id === currentTabDatasource)
	);
	const datasourceOptions = $derived.by(() => datasourceStore.datasources);
	const filteredOptions = $derived.by(() => {
		const query = search.trim().toLowerCase();
		if (!query) return datasourceOptions;
		return datasourceOptions.filter((ds) => {
			const name = ds.name.toLowerCase();
			const type = ds.source_type.toLowerCase();
			return name.includes(query) || type.includes(query);
		});
	});

	$effect(() => {
		config.sources = selectedSources;
	});

	$effect(() => {
		if (config.allow_missing === undefined) {
			config.allow_missing = true;
		}
	});

	$effect(() => {
		const selected = new Set(selectedSources);
		for (const sourceId of selectedSources) {
			if (!loadedSources.includes(sourceId)) {
				loadUnionSchema(sourceId);
			}
		}
		const removed = loadedSources.filter((id) => !selected.has(id));
		if (removed.length === 0) return;
		for (const sourceId of removed) {
			schemaStore.removeJoinDatasource(sourceId);
		}
		loadedSources = loadedSources.filter((id) => selected.has(id));
	});

	async function loadUnionSchema(datasourceId: string) {
		const schemaInfo = await datasourceStore.getSchema(datasourceId);
		const unionSchema: Schema = {
			columns: schemaInfo.columns.map((c) => ({
				name: c.name,
				dtype: c.dtype,
				nullable: c.nullable
			})),
			row_count: schemaInfo.row_count
		};
		schemaStore.setJoinDatasource(datasourceId, unionSchema);
		if (!loadedSources.includes(datasourceId)) {
			loadedSources = [...loadedSources, datasourceId];
		}
	}

	function toggleSource(sourceId: string) {
		const exists = selectedSources.includes(sourceId);
		selectedSources = exists
			? selectedSources.filter((id) => id !== sourceId)
			: [...selectedSources, sourceId];
	}

	function handlePickerFocus() {
		showPicker = true;
	}

	function handlePickerBlur() {
		setTimeout(() => {
			showPicker = false;
		}, 100);
	}

	function selectAll() {
		selectedSources = filteredOptions.map((ds) => ds.id);
	}

	function deselectAll() {
		selectedSources = [];
	}
</script>

<div class="config-panel">
	<h3>Union By Name</h3>
	<p class="description">Combine rows from multiple datasources using matching column names.</p>

	<div class="form-section">
		<h4>Base Datasource</h4>
		<div class="summary">
			{#if currentDatasource}
				<strong>{currentDatasource.name}</strong>
				<span class="meta">{schema.columns.length} columns</span>
			{:else}
				<span class="muted">No active datasource selected</span>
			{/if}
		</div>
	</div>

	<div class="form-section">
		<div class="section-header">
			<h4>Union Sources</h4>
			<div class="bulk-actions">
				<button type="button" class="btn-link" onclick={selectAll}>Select All</button>
				<button type="button" class="btn-link" onclick={deselectAll}>Deselect All</button>
			</div>
		</div>

		<div
			class="search-picker"
			role="combobox"
			aria-expanded={showPicker}
			aria-controls="union-source-options"
		>
			<span class="sr-only">Search datasources</span>
			<input
				type="text"
				placeholder="Search datasources..."
				bind:value={search}
				onfocus={handlePickerFocus}
				onblur={handlePickerBlur}
			/>
			{#if showPicker}
				<div
					class="picker-list"
					id="union-source-options"
					role="listbox"
					aria-label="Union datasource options"
				>
					{#if datasourceOptions.length === 0}
						<div class="picker-empty">Add another datasource to enable unions.</div>
					{:else if filteredOptions.length === 0}
						<div class="picker-empty">No matching datasources.</div>
					{:else}
						{#each filteredOptions as ds (ds.id)}
							<button
								type="button"
								class="picker-item"
								data-selected={selectedSources.includes(ds.id)}
								onmousedown={() => toggleSource(ds.id)}
							>
								<span class="source-name">{ds.name}</span>
								<span class="meta">{ds.source_type}</span>
							</button>
						{/each}
					{/if}
				</div>
			{/if}
		</div>

		{#if datasourceOptions.length === 0}
			<p class="empty-message">Add another datasource to enable unions.</p>
		{:else if selectedSources.length === 0}
			<p class="empty-message">No sources selected yet.</p>
		{:else}
			<div class="source-list">
				{#each datasourceOptions.filter((ds) => selectedSources.includes(ds.id)) as ds (ds.id)}
					<div class="source-chip">
						<span>{ds.name}</span>
						<button
							type="button"
							onclick={() => toggleSource(ds.id)}
							aria-label={`Remove ${ds.name}`}
						>
							×
						</button>
					</div>
				{/each}
			</div>
		{/if}

		{#if selectedSources.length === 0}
			<div class="warning-box">Select at least one datasource to union.</div>
		{/if}
	</div>

	<div class="form-section">
		<h4>Column Matching</h4>
		<label class="toggle">
			<input id="allow-missing" type="checkbox" bind:checked={config.allow_missing} />
			<span>Allow missing columns (fill with nulls)</span>
		</label>
		<p class="help-text">
			When enabled, missing columns are created with null values to keep all rows. Disable to
			require identical schemas.
		</p>
	</div>
</div>

<style>
	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--space-4);
	}
	.section-header h4 {
		margin-bottom: 0;
	}
	.summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.meta {
		color: var(--fg-tertiary);
		font-size: var(--text-xs);
	}
	.muted {
		color: var(--fg-muted);
	}
	.btn-link {
		background: none;
		border: none;
		color: var(--accent-primary);
		cursor: pointer;
		font-size: var(--text-xs);
		padding: var(--space-1);
		text-decoration: underline;
	}
	.source-list {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding: var(--space-2);
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
		border: 1px solid var(--panel-border);
	}
	.source-chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		border-radius: 999px;
		background-color: var(--bg-hover);
		font-size: var(--text-xs);
	}
	.source-chip button {
		border: none;
		background: none;
		cursor: pointer;
		line-height: 1;
		color: var(--fg-muted);
		padding: 0;
	}
	.source-chip button:hover {
		color: var(--fg-primary);
	}
	.source-name {
		flex: 1;
	}
	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.help-text {
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
		line-height: 1.5;
		margin: var(--space-2) 0 0;
		padding: var(--space-3);
		background-color: var(--form-help-bg);
		border-left: 3px solid var(--form-help-accent);
		border-radius: var(--radius-sm);
		border: 1px solid var(--form-help-border);
	}
	.empty-message {
		color: var(--fg-muted);
		font-style: italic;
		margin: var(--space-2) 0;
	}
	.search-picker {
		position: relative;
		margin-bottom: var(--space-3);
	}
	.search-picker input {
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
	}
	.search-picker input::placeholder {
		color: var(--fg-muted);
	}
	.picker-list {
		position: absolute;
		z-index: var(--z-dropdown);
		top: calc(100% + var(--space-1));
		left: 0;
		right: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-height: 220px;
		overflow-y: auto;
		padding: var(--space-2);
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
		border: 1px solid var(--panel-border);
		box-shadow: var(--shadow-dropdown);
	}
	.picker-item {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
		padding: var(--space-1) var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background-color: transparent;
		text-align: left;
	}
	.picker-item[data-selected='true'] {
		border-color: var(--accent-primary);
		background-color: var(--bg-hover);
	}
	.picker-item:hover {
		background-color: var(--bg-hover);
	}
	.picker-empty {
		padding: var(--space-2);
		color: var(--fg-muted);
		font-style: italic;
	}
</style>
