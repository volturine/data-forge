<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { UnionByNameConfigData } from '$lib/types/operation-config';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, stepConfig, label } from '$lib/styles/panda';
	import { SvelteSet } from 'svelte/reactivity';

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

	const loaded = new SvelteSet<string>();
	let pending = $state(0);
	let schemaErrors = $state.raw<Record<string, string>>({});
	const loading = $derived(pending > 0);
	const schemaErrorList = $derived(
		Object.entries(schemaErrors).map(([id, message]) => ({ id, message }))
	);

	async function loadSourceSchema(
		datasourceId: string,
		options: { forceRefresh?: boolean } = {}
	) {
		loaded.add(datasourceId);
		pending += 1;
		if (options.forceRefresh) {
			datasourceStore.clearSchemaCache(datasourceId);
		}
		try {
			// Cache-first: join/union config only needs column metadata, not re-ingest.
			const schemaInfo = await datasourceStore.getSchema(datasourceId, {
				refresh: options.forceRefresh === true
			});
			const unionSchema: Schema = {
				columns: schemaInfo.columns.map((c) => ({
					name: c.name,
					dtype: c.dtype,
					nullable: c.nullable
				})),
				row_count: schemaInfo.row_count
			};
			schemaStore.setJoinDatasource(datasourceId, unionSchema);
			const { [datasourceId]: _removed, ...rest } = schemaErrors;
			schemaErrors = rest;
		} catch (err) {
			loaded.delete(datasourceId);
			schemaErrors = {
				...schemaErrors,
				[datasourceId]: err instanceof Error ? err.message : 'Failed to load schema'
			};
		} finally {
			pending -= 1;
		}
	}

	function removeSourceSchema(datasourceId: string) {
		loaded.delete(datasourceId);
		schemaStore.removeJoinDatasource(datasourceId);
		const { [datasourceId]: _removed, ...rest } = schemaErrors;
		schemaErrors = rest;
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

		{#each schemaErrorList as entry (entry.id)}
			<div class={css({ marginTop: '2', display: 'flex', flexDirection: 'column', gap: '2' })}>
				<Callout tone="error">
					Failed to load schema for source {entry.id}: {entry.message}
				</Callout>
				<button
					type="button"
					class={css({
						alignSelf: 'flex-start',
						paddingY: '1',
						paddingX: '3',
						borderWidth: '1',
						cursor: 'pointer',
						fontSize: 'sm',
						backgroundColor: 'bg.secondary',
						_hover: { backgroundColor: 'bg.hover' }
					})}
					data-testid={`union-schema-retry-${entry.id}`}
					onclick={() => void loadSourceSchema(entry.id, { forceRefresh: true })}
				>
					Retry
				</button>
			</div>
		{/each}
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
