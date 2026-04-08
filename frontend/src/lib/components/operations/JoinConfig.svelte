<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { JoinConfigData } from '$lib/types/operation-config';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { X } from 'lucide-svelte';
	import { css, stepConfig, cx, label, input } from '$lib/styles/panda';

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

	// Use config.right_source directly as single source of truth
	let loadedRightSource = $state('');
	let rightSchema = $state<Schema | null>(null);
	const rightColumns = $derived(rightSchema?.columns ?? []);

	const isCrossJoin = $derived(config.how === 'cross');

	// Load right schema when config.right_source changes
	// Network: $derived can't fetch schema for selected datasource.
	$effect(() => {
		const source = config.right_source;
		if (source && source !== loadedRightSource) {
			loadedRightSource = source;
			loadRightSchema(source);
		}
	});

	async function loadRightSchema(datasourceId: string) {
		const target = datasourceStore.getDatasource(datasourceId);
		if (target?.source_type === 'analysis') {
			rightSchema = null;
			return;
		}
		let schemaInfo: Awaited<ReturnType<typeof datasourceStore.getSchema>> | null;
		try {
			schemaInfo = await datasourceStore.getSchema(datasourceId);
		} catch (err) {
			void err;
			schemaInfo = null;
		}
		if (!schemaInfo) {
			rightSchema = null;
			schemaStore.removeJoinDatasource(datasourceId);
			return;
		}
		const joinSchema: Schema = {
			columns: schemaInfo.columns.map((c) => ({
				name: c.name,
				dtype: c.dtype,
				nullable: c.nullable
			})),
			row_count: schemaInfo.row_count
		};
		rightSchema = joinSchema;
		schemaStore.setJoinDatasource(datasourceId, joinSchema);
	}

	function addJoinColumn() {
		const columns = config.join_columns ?? [];
		const randomId =
			typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
				? crypto.randomUUID().substring(0, 8)
				: 'id-' + Math.random().toString(16).slice(2) + Date.now().toString(16).slice(-8);
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
			onSelect={(id) => {
				config.right_source = id;
				loadRightSchema(id);
			}}
		/>
		{#if rightSchema}
			<div
				id="join-schema-preview"
				class={css({ marginTop: '2', fontSize: 'xs', color: 'fg.muted' })}
				aria-live="polite"
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
						_hover: { backgroundColor: 'accent.primary' }
					})}
					onclick={addJoinColumn}
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
					<div class={css({ flex: '1' })}>
						<label for={`join-left-${joinCol.id}`} class={cx(label(), css({ marginBottom: '1' }))}
							>Left Column</label
						>
						<ColumnDropdown
							{schema}
							value={joinCol.left_column ?? ''}
							onChange={(val) => (joinCol.left_column = val)}
							placeholder="Select..."
						/>
					</div>
					<div class={css({ flex: '1' })}>
						<label for={`join-right-${joinCol.id}`} class={cx(label(), css({ marginBottom: '1' }))}
							>Right Column</label
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

		{#if rightColumns.length === 0}
			<p
				class={css({
					color: 'fg.muted',
					fontStyle: 'italic',
					textAlign: 'center',
					padding: '4',
					margin: '0'
				})}
			>
				Select a right datasource first
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
		<span id="join-suffix-hint" class={cx(label(), css({ marginTop: '1' }))}>
			Suffix for columns from the right dataset (when names collide)
		</span>
	</div>
</div>
