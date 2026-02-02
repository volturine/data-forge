<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';

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

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource_id ?? null);
	const currentDatasource = $derived(
		datasourceStore.datasources.find((ds) => ds.id === currentTabDatasource)
	);
	const datasourceOptions = $derived.by(() => datasourceStore.datasources);

	// Sync selectedSources with config.sources
	$effect(() => {
		config.sources = selectedSources;
	});

	// Load schemas for selected sources
	$effect(() => {
		const selected = new Set(selectedSources);
		for (const sourceId of selectedSources) {
			if (!loadedSources.includes(sourceId)) {
				loadSourceSchema(sourceId);
			}
		}
		const removed = loadedSources.filter((id) => !selected.has(id));
		if (removed.length === 0) return;
		for (const sourceId of removed) {
			schemaStore.removeJoinDatasource(sourceId);
		}
		loadedSources = loadedSources.filter((id) => selected.has(id));
	});

	async function loadSourceSchema(datasourceId: string) {
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
		</div>

		{#if datasourceOptions.length === 0}
			<p class="empty-message">Add another datasource to enable unions.</p>
		{:else}
			<DatasourcePicker
				datasources={datasourceOptions}
				bind:selected={selectedSources}
				mode="multi"
				id="union"
				showChips={true}
				showBulkActions={true}
				onSelect={(id) => loadSourceSchema(id)}
			/>
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
</style>
