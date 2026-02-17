<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { JoinConfigData } from '$lib/types/operation-config';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import { X } from 'lucide-svelte';

	const uid = $props.id();

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
	let rightColumns = $derived(rightSchema?.columns ?? []);

	const isCrossJoin = $derived(config.how === 'cross');

	// Load right schema when config.right_source changes
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
		let schemaInfo: Awaited<ReturnType<typeof datasourceStore.getSchema>> | null = null;
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

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource_id);
	const datasourceOptions = $derived.by(() =>
		datasourceStore.datasources.filter((ds) => ds.source_type !== 'analysis')
	);
</script>

<div class="config-panel" role="region" aria-label="Join configuration">
	<h3>Join Configuration</h3>

	<div class="form-section" role="group" aria-labelledby="right-datasource-heading">
		<h4 id="right-datasource-heading">Right Datasource</h4>
		<DatasourcePicker
			datasources={datasourceOptions}
			selected={config.right_source ?? ''}
			mode="single"
			id={uid}
			highlightId={currentTabDatasource ?? undefined}
			onSelect={(id) => {
				config.right_source = id;
				loadRightSchema(id);
			}}
		/>
		{#if rightSchema}
			<div id="join-schema-preview" class="mt-2 p-2 bg-panel" aria-live="polite">
				<strong>{rightSchema.columns.length} columns</strong>
			</div>
		{/if}
	</div>

	<div class="form-section" role="group" aria-labelledby="join-type-heading">
		<h4 id="join-type-heading">Join Type</h4>
		<label for="join-select-type" class="sr-only">Select join type</label>
		<select id="join-select-type" data-testid="join-type-select" bind:value={config.how}>
			{#each joinTypes as joinType (joinType.value)}
				<option value={joinType.value}>{joinType.label}</option>
			{/each}
		</select>
		<div
			id="join-type-help"
			class="help-box text-sm leading-relaxed p-3 mt-2"
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
		<div class="form-section" role="group" aria-labelledby="join-columns-heading">
			<div class="flex justify-between items-center mb-4">
				<h4 id="join-columns-heading" class="mb-0">Join Columns</h4>
				<button
					id="join-btn-add-column"
					data-testid="join-add-column-button"
					type="button"
					class="btn-add py-1 px-3 border-none cursor-pointer text-sm bg-accent text-bg-primary hover:bg-accent-primary"
					onclick={addJoinColumn}
					aria-label="Add join column pair"
				>
					+ Add Join Column
				</button>
			</div>

			{#if (config.join_columns ?? []).length === 0}
				<p id="join-columns-empty" class="empty-message">
					No join columns configured. Click "+ Add Join Column" to add one.
				</p>
			{/if}

			{#each config.join_columns ?? [] as joinCol, _index (joinCol.id)}
				<div
					class="flex gap-2 items-end mb-3 p-3 bg-panel"
					role="group"
					aria-label={`Join column pair ${_index + 1}`}
				>
					<div class="flex-1">
						<label for={`join-left-${joinCol.id}`} class="block text-xs mb-1 text-fg-muted"
							>Left Column</label
						>
						<ColumnDropdown
							{schema}
							value={joinCol.left_column ?? ''}
							onChange={(val) => (joinCol.left_column = val)}
							placeholder="Select..."
						/>
					</div>
					<div class="flex-1">
						<label for={`join-right-${joinCol.id}`} class="block text-xs mb-1 text-fg-muted"
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
						class="btn-remove p-2 bg-transparent cursor-pointer text-error-fg border border-error hover:bg-error"
						onclick={() => removeJoinColumn(joinCol.id)}
						aria-label={`Remove join column pair ${_index + 1}`}
					>
						<X size={14} />
					</button>
				</div>
			{/each}

			{#if (config.join_columns ?? []).length > 0}
				{#if !(config.join_columns ?? []).some((c) => c.left_column && c.right_column)}
					<div id="join-columns-warning" class="warning-box" role="alert">
						Configure at least one join column pair
					</div>
				{/if}
			{/if}
		</div>
	{/if}

	<div class="form-section" role="group" aria-labelledby="right-columns-heading">
		<h4 id="right-columns-heading">Columns from Right Dataset</h4>

		{#if rightColumns.length === 0}
			<p class="empty-message">Select a right datasource first</p>
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
			<div id="join-right-columns-warning" class="warning-box" role="alert">
				Select at least one column from the right dataset
			</div>
		{/if}
	</div>
	<div class="form-section" role="group" aria-labelledby="suffix-heading">
		<h4 id="suffix-heading">Column Suffix</h4>
		<label for="join-input-suffix" class="sr-only">Suffix for right dataset columns</label>
		<input
			id="join-input-suffix"
			data-testid="join-suffix-input"
			type="text"
			bind:value={config.suffix}
			placeholder="_right"
			aria-describedby="join-suffix-hint"
		/>
		<div id="join-suffix-hint" class="help-box text-sm leading-relaxed p-3 mt-2">
			Suffix for columns from the right dataset (when names collide)
		</div>
	</div>
</div>
