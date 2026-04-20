<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, stepConfig, label } from '$lib/styles/panda';

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

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource.id ?? null);
	const currentDatasource = $derived(
		datasourceStore.datasources.find((ds) => ds.id === currentTabDatasource)
	);
	const datasourceOptions = $derived(datasourceStore.datasources);
	const ready = $derived(datasourceStore.loaded);

	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- bookkeeping only, never read by template
	const loaded = new Set<string>();
	let pending = $state(0);
	const loading = $derived(pending > 0);

	async function loadSourceSchema(datasourceId: string) {
		loaded.add(datasourceId);
		pending += 1;
		try {
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
		} catch {
			loaded.delete(datasourceId);
		} finally {
			pending -= 1;
		}
	}

	function removeSourceSchema(datasourceId: string) {
		loaded.delete(datasourceId);
		schemaStore.removeJoinDatasource(datasourceId);
	}

	// Network: $derived can't trigger async schema loads for pre-populated or externally-changed sources.
	$effect(() => {
		const current = new Set(config.sources);
		for (const id of current) {
			if (!loaded.has(id)) void loadSourceSchema(id);
		}
		const stale = [...loaded].filter((id) => !current.has(id));
		for (const id of stale) {
			removeSourceSchema(id);
		}
	});
</script>

<div class={stepConfig()} data-ready={ready || undefined} data-loading={loading || undefined}>
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
				<span class={css({ color: 'fg.muted' })}>No active datasource selected</span>
			{/if}
		</div>
	</div>

	<div
		class={css(
			{
				marginBottom: '0',
				paddingBottom: '5',
				backgroundColor: 'transparent',

				border: 'none'
			},
			{ borderTopWidth: '1', paddingTop: '5' }
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
				bind:selected={config.sources}
				mode="multi"
				showChips={true}
				showBulkActions={true}
				onSelect={(id) => void loadSourceSchema(id)}
				onDeselect={(id) => removeSourceSchema(id)}
			/>
		{/if}

		{#if config.sources.length === 0}
			<Callout tone="warn">Select at least one datasource to union.</Callout>
		{/if}
	</div>

	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none',
			borderTopWidth: '1',
			paddingTop: '5'
		})}
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
