<script lang="ts">
	import { onMount } from 'svelte';
	import type { Schema } from '$lib/types/schema';
	import type { JoinConfigData } from '$lib/types/operation-config';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { uuid } from '$lib/utils/uuid';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { X } from '@lucide/svelte';
	import { css, stepConfig, label, input, button } from '$lib/styles/panda';

	const _uid = $props.id();

	const defaultConfig: JoinConfigData = {
		how: 'inner',
		right_source: '',
		join_columns: [],
		right_columns: [],
		suffix: '_right'
	};

	interface Props {
		schema: Schema;
		config?: JoinConfigData;
	}

	let { schema, config = $bindable(defaultConfig) }: Props = $props();

	let rightSchema = $state<Schema | null>(null);
	let rightSchemaLoading = $state(false);
	let rightSchemaError = $state<string | null>(null);
	let loadGeneration = 0;

	const hasRightSource = $derived(Boolean(config.right_source));
	const rightColumns = $derived(rightSchema?.columns ?? []);
	const isCrossJoin = $derived(config.how === 'cross');

	onMount(() => {
		const source = config.right_source ?? '';
		if (!source) return;
		void loadRightSchema(source);
	});

	async function loadRightSchema(
		datasourceId: string,
		options: { forceRefresh?: boolean } = {}
	): Promise<void> {
		const generation = ++loadGeneration;
		const target = datasourceStore.getDatasource(datasourceId);
		if (target?.source_type === 'analysis') {
			if (generation !== loadGeneration) return;
			rightSchema = null;
			rightSchemaError = 'Analysis outputs cannot be used as a join right source';
			rightSchemaLoading = false;
			schemaStore.removeJoinDatasource(datasourceId);
			return;
		}

		rightSchemaLoading = true;
		rightSchemaError = null;
		if (options.forceRefresh) {
			datasourceStore.clearSchemaCache(datasourceId);
		}

		try {
			const schemaInfo = await datasourceStore.getSchema(datasourceId, {
				refresh: options.forceRefresh === true
			});
			if (generation !== loadGeneration) return;
			const joinSchema: Schema = {
				columns: schemaInfo.columns.map((c) => ({
					name: c.name,
					dtype: c.dtype,
					nullable: c.nullable
				})),
				row_count: schemaInfo.row_count
			};
			rightSchema = joinSchema;
			rightSchemaError = null;
			schemaStore.setJoinDatasource(datasourceId, joinSchema);
		} catch (err) {
			if (generation !== loadGeneration) return;
			rightSchema = null;
			rightSchemaError = err instanceof Error ? err.message : 'Failed to load schema';
			schemaStore.removeJoinDatasource(datasourceId);
		} finally {
			if (generation === loadGeneration) {
				rightSchemaLoading = false;
			}
		}
	}

	function retryRightSchema(): void {
		const source = config.right_source;
		if (!source) return;
		void loadRightSchema(source, { forceRefresh: true });
	}

	function selectRightSource(id: string): void {
		config.right_source = id;
		if (!id) {
			rightSchema = null;
			rightSchemaError = null;
			rightSchemaLoading = false;
			return;
		}
		void loadRightSchema(id);
	}

	function addJoinColumn() {
		const columns = config.join_columns ?? [];
		const randomId = uuid().slice(0, 8);
		config.join_columns = [...columns, { id: randomId, left_column: '', right_column: '' }];
	}

	function removeJoinColumn(id: string) {
		const columns = config.join_columns ?? [];
		config.join_columns = columns.filter((col) => col.id !== id);
	}

	const joinTypes: Array<{ value: JoinConfigData['how']; label: string }> = [
		{ value: 'inner', label: 'Inner Join' },
		{ value: 'left', label: 'Left Join' },
		{ value: 'right', label: 'Right Join' },
		{ value: 'outer', label: 'Outer Join' },
		{ value: 'cross', label: 'Cross Join' }
	];

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource.id ?? null);
	const datasourceOptions = $derived(
		datasourceStore.datasources.filter((ds) => ds.source_type !== 'analysis')
	);
</script>

<div class={stepConfig()} role="region" aria-label="Join configuration">
	<div
		class={css({
			marginBottom: '0',
			paddingBottom: '5',
			backgroundColor: 'transparent',

			border: 'none'
		})}
		role="group"
		aria-labelledby="right-datasource-heading"
	>
		<span id="right-datasource-heading"><SectionHeader>Right Datasource</SectionHeader></span>
		<DatasourcePicker
			datasources={datasourceOptions}
			selected={config.right_source ?? ''}
			mode="single"
			highlightId={currentTabDatasource ?? undefined}
			onSelect={selectRightSource}
		/>
		{#if rightSchemaLoading}
			<div
				id="join-schema-preview"
				class={css({ marginTop: '2', fontSize: 'xs', color: 'fg.muted' })}
				aria-live="polite"
				data-testid="join-schema-loading"
			>
				Loading schema…
			</div>
		{:else if rightSchemaError}
			<div class={css({ marginTop: '2', display: 'flex', flexDirection: 'column', gap: '2' })}>
				<Callout tone="error">{rightSchemaError}</Callout>
				<button
					type="button"
					class={button({ variant: 'secondary', size: 'sm' })}
					data-testid="join-schema-retry"
					onclick={retryRightSchema}
				>
					Retry schema load
				</button>
			</div>
		{:else if rightSchema}
			<div
				id="join-schema-preview"
				class={css({ marginTop: '2', fontSize: 'xs', color: 'fg.muted' })}
				aria-live="polite"
				data-testid="join-schema-ready"
			>
				{rightSchema.columns.length} columns available
			</div>
		{/if}
	</div>

	<div
		class={css({
			borderTopWidth: '1',
			marginBottom: '0',
			paddingBottom: '5',
			paddingTop: '5',
			backgroundColor: 'transparent'
		})}
		role="group"
		aria-labelledby="join-type-heading"
	>
		<span id="join-type-heading"><SectionHeader>Join Type</SectionHeader></span>
		<label for="join-select-type" class={label({ variant: 'hidden' })}>Select join type</label>
		<select
			id="join-select-type"
			class={input()}
			data-testid="join-type-select"
			bind:value={config.how}
		>
			{#each joinTypes as joinType (joinType.value)}
				<option value={joinType.value}>{joinType.label}</option>
			{/each}
		</select>
		<div
			id="join-type-help"
			class={css({
				color: 'fg.tertiary',
				backgroundColor: 'transparent',
				border: 'none',
				borderLeftWidth: '2',
				fontSize: 'xs',
				paddingX: '3',
				paddingY: '2',
				lineHeight: 'relaxed',
				marginTop: '3'
			})}
			aria-describedby="join-type-help"
		>
			<strong>Inner:</strong> Only matching rows from both.<br />
			<strong>Left:</strong> All left rows, matching right rows.<br />
			<strong>Right:</strong> All right rows, matching left rows.<br />
			<strong>Outer:</strong> All rows from both.<br />
			<strong>Cross:</strong> Cartesian product (no keys needed).
		</div>
	</div>

	{#if !isCrossJoin}
		<div
			class={css({
				borderTopWidth: '1',
				marginBottom: '0',
				paddingBottom: '5',
				paddingTop: '5',
				backgroundColor: 'transparent'
			})}
			role="group"
			aria-labelledby="join-columns-heading"
		>
			<div
				class={css({
					display: 'flex',
					justifyContent: 'space-between',
					alignItems: 'center',
					marginBottom: '5'
				})}
			>
				<span id="join-columns-heading"><SectionHeader>Join Columns</SectionHeader></span>
				<button
					id="join-btn-add-column"
					data-testid="join-add-column-button"
					type="button"
					class={css({
						paddingY: '1',
						paddingX: '3',
						border: 'none',
						cursor: 'pointer',
						fontSize: 'sm',
						backgroundColor: 'bg.accent',
						color: 'fg.inverse',
						_hover: { backgroundColor: 'accent.primary' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed' }
					})}
					onclick={addJoinColumn}
					disabled={!hasRightSource || rightSchemaLoading || !!rightSchemaError}
					aria-label="Add join column pair"
				>
					+ Add Join Column
				</button>
			</div>

			{#if (config.join_columns ?? []).length === 0}
				<p
					id="join-columns-empty"
					class={css({
						color: 'fg.muted',
						fontStyle: 'italic',
						textAlign: 'center',
						padding: '4',
						margin: '0'
					})}
				>
					No join columns configured. Click "+ Add Join Column" to add one.
				</p>
			{/if}

			{#each config.join_columns ?? [] as joinCol, _index (joinCol.id)}
				<div
					class={css({
						display: 'flex',
						gap: '3',
						alignItems: 'end',
						marginBottom: '3',
						borderLeftWidth: '2',
						paddingLeft: '4',
						paddingBottom: '3'
					})}
					role="group"
					aria-label={`Join column pair ${_index + 1}`}
				>
					<div class={css({ flex: '1' })} role="group" aria-label="Left Column">
						<label
							for={`join-left-${joinCol.id}`}
							class={css({
								display: 'block',
								fontSize: 'xs2',
								fontWeight: 'semibold',
								color: 'fg.muted',
								marginBottom: '1',
								textTransform: 'uppercase',
								letterSpacing: 'wider'
							})}>Left Column</label
						>
						<ColumnDropdown
							{schema}
							value={joinCol.left_column ?? ''}
							onChange={(val) => (joinCol.left_column = val)}
							placeholder="Select..."
						/>
					</div>
					<div class={css({ flex: '1' })} role="group" aria-label="Right Column">
						<label
							for={`join-right-${joinCol.id}`}
							class={css({
								display: 'block',
								fontSize: 'xs2',
								fontWeight: 'semibold',
								color: 'fg.muted',
								marginBottom: '1',
								textTransform: 'uppercase',
								letterSpacing: 'wider'
							})}>Right Column</label
						>
						<ColumnDropdown
							schema={{ columns: rightColumns, row_count: rightSchema?.row_count ?? 0 }}
							value={joinCol.right_column ?? ''}
							onChange={(val) => (joinCol.right_column = val)}
							placeholder="Select..."
						/>
					</div>
					<button
						id={`join-btn-remove-${_index}`}
						data-testid={`join-remove-button-${_index}`}
						type="button"
						class={css({
							padding: '2',
							backgroundColor: 'transparent',
							cursor: 'pointer',
							color: 'fg.error',
							borderWidth: '1',
							borderColor: 'border.error',
							_hover: { backgroundColor: 'bg.error' }
						})}
						onclick={() => removeJoinColumn(joinCol.id)}
						aria-label={`Remove join column pair ${_index + 1}`}
					>
						<X size={14} />
					</button>
				</div>
			{/each}

			{#if (config.join_columns ?? []).length > 0}
				{#if !(config.join_columns ?? []).some((c) => c.left_column && c.right_column)}
					<Callout tone="warn">Configure at least one join column pair</Callout>
				{/if}
			{/if}
		</div>
	{/if}

	<div
		class={css({
			borderTopWidth: '1',
			marginBottom: '0',
			paddingBottom: '5',
			paddingTop: '5',
			backgroundColor: 'transparent'
		})}
		role="group"
		aria-labelledby="right-columns-heading"
	>
		<span id="right-columns-heading"><SectionHeader>Columns from Right Dataset</SectionHeader></span
		>

		{#if !hasRightSource}
			<p
				class={css({
					color: 'fg.muted',
					fontStyle: 'italic',
					textAlign: 'center',
					padding: '4',
					margin: '0'
				})}
				data-testid="join-right-columns-empty"
			>
				Select a right datasource first
			</p>
		{:else if rightSchemaLoading}
			<p
				class={css({
					color: 'fg.muted',
					fontStyle: 'italic',
					textAlign: 'center',
					padding: '4',
					margin: '0'
				})}
				data-testid="join-right-columns-loading"
			>
				Loading right datasource schema…
			</p>
		{:else if rightSchemaError}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
				<Callout tone="error">Could not load right datasource schema: {rightSchemaError}</Callout>
				<button
					type="button"
					class={button({ variant: 'secondary', size: 'sm' })}
					data-testid="join-right-columns-retry"
					onclick={retryRightSchema}
				>
					Retry
				</button>
			</div>
		{:else if rightColumns.length === 0}
			<p
				class={css({
					color: 'fg.muted',
					fontStyle: 'italic',
					textAlign: 'center',
					padding: '4',
					margin: '0'
				})}
			>
				Right datasource has no columns
			</p>
		{:else}
			<MultiSelectColumnDropdown
				schema={{ columns: rightColumns, row_count: rightSchema?.row_count ?? 0 }}
				value={config.right_columns ?? []}
				onChange={(val) => (config.right_columns = val)}
				showSelectAll={true}
				placeholder="Select columns from right dataset..."
			/>
		{/if}

		{#if rightColumns.length > 0 && (config.right_columns ?? []).length === 0}
			<Callout tone="warn">Select at least one column from the right dataset</Callout>
		{/if}
	</div>
	<div
		class={css({
			borderTopWidth: '1',
			marginBottom: '0',
			paddingBottom: '5',
			paddingTop: '5',
			backgroundColor: 'transparent'
		})}
		role="group"
		aria-labelledby="suffix-heading"
	>
		<span id="suffix-heading"><SectionHeader>Column Suffix</SectionHeader></span>
		<label for="join-input-suffix" class={label({ variant: 'hidden' })}
			>Suffix for right dataset columns</label
		>
		<input
			id="join-input-suffix"
			data-testid="join-suffix-input"
			type="text"
			class={input()}
			bind:value={config.suffix}
			placeholder="_right"
			aria-describedby="join-suffix-hint"
		/>
		<span
			id="join-suffix-hint"
			class={css({
				display: 'block',
				fontSize: 'xs2',
				fontWeight: 'semibold',
				color: 'fg.muted',
				marginBottom: '1.5',
				textTransform: 'uppercase',
				letterSpacing: 'wider',
				marginTop: '1'
			})}
		>
			Suffix for columns from the right dataset (when names collide)
		</span>
	</div>
</div>
