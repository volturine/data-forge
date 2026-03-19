<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, cx, stepConfig, label, divider, muted } from '$lib/styles/panda';

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

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource.id ?? null);
	const currentDatasource = $derived(
		datasourceStore.datasources.find((ds) => ds.id === currentTabDatasource)
	);
	const datasourceOptions = $derived(datasourceStore.datasources);

	// Sync selectedSources with config.sources
	// Subscription: $derived can't sync selected sources to config.
	$effect(() => {
		config.sources = selectedSources;
	});

	// Load schemas for selected sources
	// Network: $derived can't fetch source schemas.
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

<div class={stepConfig()}>
	<p
		class={css({
			marginTop: '0',
			marginBottom: '3',
			color: 'fg.tertiary',
			fontSize: 'xs',
			lineHeight: 'base'
		})}
	>
		Combine rows from multiple datasources using matching column names.
	</p>

	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
	>
		<SectionHeader>Base Datasource</SectionHeader>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
			{#if currentDatasource}
				<strong>{currentDatasource.name}</strong>
				<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}
					>{schema.columns.length} columns</span
				>
			{:else}
				<span class={muted}>No active datasource selected</span>
			{/if}
		</div>
	</div>

	<div
		class={cx(
			css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			}),
			cx(
				divider,
				css({
					paddingTop: '5'
				})
			)
		)}
	>
		<div
			class={css({
				display: 'flex',
				justifyContent: 'space-between',
				alignItems: 'center',
				marginBottom: '5'
			})}
		>
			<SectionHeader>Union Sources</SectionHeader>
		</div>

		{#if datasourceOptions.length === 0}
			<p class={css({ marginY: '2', fontStyle: 'italic', color: 'fg.muted' })}>
				Add another datasource to enable unions.
			</p>
		{:else}
			<DatasourcePicker
				datasources={datasourceOptions}
				bind:selected={selectedSources}
				mode="multi"
				showChips={true}
				showBulkActions={true}
				onSelect={(id) => loadSourceSchema(id)}
			/>
		{/if}

		{#if selectedSources.length === 0}
			<Callout tone="warn">Select at least one datasource to union.</Callout>
		{/if}
	</div>

	<div
		class={cx(
			css({
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			}),
			cx(
				divider,
				css({
					paddingTop: '5'
				})
			)
		)}
	>
		<SectionHeader>Column Matching</SectionHeader>
		<label class={label({ variant: 'checkbox' })}>
			<input id="allow-missing" type="checkbox" bind:checked={config.allow_missing} />
			<span>Allow missing columns (fill with nulls)</span>
		</label>
		<span
			class={css({
				marginTop: '2',
				display: 'block',
				fontSize: 'xs',
				color: 'fg.muted',
				lineHeight: 'relaxed'
			})}
		>
			When enabled, missing columns are created with null values to keep all rows.
		</span>
	</div>
</div>
