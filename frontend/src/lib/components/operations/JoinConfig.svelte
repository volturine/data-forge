<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { JoinConfigData } from '$lib/types/operation-config';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';

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

	let selectedRightSource = $state(config.right_source ?? '');
	let loadedRightSource = $state('');
	let rightSchema = $state<Schema | null>(null);
	let rightColumns = $derived(rightSchema?.columns ?? []);

	const isCrossJoin = $derived(config.how === 'cross');

	$effect(() => {
		config.right_source = selectedRightSource;
	});

	$effect(() => {
		const targetSource = config.right_source || selectedRightSource;
		if (config.right_source && config.right_source !== selectedRightSource) {
			selectedRightSource = config.right_source;
		}
		if (targetSource && targetSource !== loadedRightSource) {
			loadedRightSource = targetSource;
			loadRightSchema(targetSource);
		}
	});

	async function loadRightSchema(datasourceId: string) {
		const schemaInfo = await datasourceStore.getSchema(datasourceId);
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

	function toggleRightColumn(columnName: string) {
		const rightCols = config.right_columns ?? [];
		if (rightCols.includes(columnName)) {
			config.right_columns = rightCols.filter((c) => c !== columnName);
		} else {
			config.right_columns = [...rightCols, columnName];
		}
	}

	function selectAllRightColumns() {
		config.right_columns = rightColumns.map((c) => c.name);
	}

	function deselectAllRightColumns() {
		config.right_columns = [];
	}

	const joinTypes: Array<{ value: JoinConfigData['how']; label: string }> = [
		{ value: 'inner', label: 'Inner Join' },
		{ value: 'left', label: 'Left Join' },
		{ value: 'right', label: 'Right Join' },
		{ value: 'outer', label: 'Outer Join' },
		{ value: 'cross', label: 'Cross Join' }
	];

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource_id ?? null);
	const currentDatasource = $derived(
		datasourceStore.datasources.find((ds) => ds.id === currentTabDatasource)
	);
</script>

<div class="join-config">
	<h3>Join Configuration</h3>

	<div class="section">
		<h4>Right Datasource</h4>
		<select bind:value={selectedRightSource}>
			<option value="">-- Select datasource --</option>
			{#if currentDatasource}
				<option value={currentDatasource.id}>
					{currentDatasource.name} (current)
				</option>
			{/if}
			{#each datasourceStore.datasources as ds (ds.id)}
				{#if ds.id !== currentTabDatasource}
					<option value={ds.id}>{ds.name} ({ds.source_type})</option>
				{/if}
			{/each}
		</select>
		{#if rightSchema}
			<div class="schema-preview">
				<strong>{rightSchema.columns.length} columns</strong>
			</div>
		{/if}
	</div>

	<div class="section">
		<h4>Join Type</h4>
		<select bind:value={config.how}>
			{#each joinTypes as joinType (joinType.value)}
				<option value={joinType.value}>{joinType.label}</option>
			{/each}
		</select>
		<div class="help-text">
			<strong>Inner:</strong> Only matching rows from both.<br />
			<strong>Left:</strong> All left rows, matching right rows.<br />
			<strong>Right:</strong> All right rows, matching left rows.<br />
			<strong>Outer:</strong> All rows from both.<br />
			<strong>Cross:</strong> Cartesian product (no keys needed).
		</div>
	</div>

	{#if !isCrossJoin}
		<div class="section">
			<div class="section-header">
				<h4>Join Columns</h4>
				<button type="button" class="btn-add" onclick={addJoinColumn}> + Add Join Column </button>
			</div>

			{#if (config.join_columns ?? []).length === 0}
				<p class="empty-message">
					No join columns configured. Click "+ Add Join Column" to add one.
				</p>
			{/if}

			{#each config.join_columns ?? [] as joinCol, _index (joinCol.id)}
				<div class="join-column-row">
					<div class="column-select">
				<label for={`join-left-${joinCol.id}`}>Left Column</label>
				<select id={`join-left-${joinCol.id}`} bind:value={joinCol.left_column}>
					<option value="">Select...</option>
					{#each schema.columns as col (col.name)}
						<option value={col.name}>{col.name}</option>
					{/each}
				</select>
			</div>
			<div class="column-select">
				<label for={`join-right-${joinCol.id}`}>Right Column</label>
				<select id={`join-right-${joinCol.id}`} bind:value={joinCol.right_column}>
					<option value="">Select...</option>
					{#each rightColumns as col (col.name)}
						<option value={col.name}>{col.name}</option>
							{/each}
						</select>
					</div>
					<button type="button" class="btn-remove" onclick={() => removeJoinColumn(joinCol.id)}>
						✕
					</button>
				</div>
			{/each}

			{#if (config.join_columns ?? []).length > 0}
				{#if !(config.join_columns ?? []).some((c) => c.left_column && c.right_column)}
					<div class="warning">Configure at least one join column pair</div>
				{/if}
			{/if}
		</div>
	{/if}

	<div class="section">
		<div class="section-header">
			<h4>Columns from Right Dataset</h4>
			<div class="column-actions">
				<button type="button" class="btn-link" onclick={selectAllRightColumns}>Select All</button>
				<button type="button" class="btn-link" onclick={deselectAllRightColumns}
					>Deselect All</button
				>
			</div>
		</div>

		{#if rightColumns.length === 0}
			<p class="empty-message">Select a right datasource first</p>
		{:else}
			<div class="column-list">
				{#each rightColumns as col (col.name)}
					<label class="column-checkbox">
						<input
							type="checkbox"
							checked={(config.right_columns ?? []).includes(col.name)}
							onchange={() => toggleRightColumn(col.name)}
						/>
						<span>{col.name}</span>
						<span class="dtype">{col.dtype}</span>
					</label>
				{/each}
			</div>
		{/if}

		{#if rightColumns.length > 0 && (config.right_columns ?? []).length === 0}
			<div class="warning">Select at least one column from the right dataset</div>
		{/if}
	</div>

	<div class="section">
		<h4>Column Suffix</h4>
		<input type="text" bind:value={config.suffix} placeholder="_right" />
		<div class="help-text">Suffix for columns from the right dataset (when names collide)</div>
	</div>
</div>

<style>
	.join-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		color: var(--panel-header-fg);
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.75rem;
		font-size: 1rem;
		color: var(--fg-secondary);
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: var(--form-section-bg);
		border-radius: var(--radius-md);
		border: 1px solid var(--form-section-border);
	}

	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1rem;
	}

	.column-actions {
		display: flex;
		gap: 0.5rem;
	}

	.section select,
	.section input {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		margin-bottom: 0.5rem;
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.join-column-row {
		display: flex;
		gap: 0.5rem;
		align-items: flex-end;
		margin-bottom: 0.75rem;
		padding: 0.75rem;
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
	}

	.column-select {
		flex: 1;
	}

	.column-select label {
		display: block;
		font-size: 0.75rem;
		margin-bottom: 0.25rem;
		color: var(--fg-muted);
	}

	.column-select select {
		margin-bottom: 0;
	}

	.btn-add {
		padding: 0.25rem 0.75rem;
		background-color: var(--primary-bg);
		color: var(--primary-fg);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.875rem;
	}

	.btn-add:hover {
		background-color: var(--primary-hover);
	}

	.btn-remove {
		padding: 0.5rem;
		background-color: transparent;
		color: var(--error-fg);
		border: 1px solid var(--error-fg);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.btn-remove:hover {
		background-color: var(--error-bg);
	}

	.btn-link {
		background: none;
		border: none;
		color: var(--primary-fg);
		cursor: pointer;
		font-size: 0.75rem;
		padding: 0.25rem;
		text-decoration: underline;
	}

	.column-list {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: 0.5rem;
		max-height: 200px;
		overflow-y: auto;
		padding: 0.5rem;
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
	}

	.column-checkbox {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.875rem;
		cursor: pointer;
	}

	.column-checkbox input {
		margin: 0;
		width: auto;
	}

	.dtype {
		color: var(--fg-muted);
		font-size: 0.75rem;
		margin-left: auto;
	}

	.schema-preview {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
	}

	.help-text {
		font-size: 0.875rem;
		color: var(--fg-tertiary);
		line-height: 1.5;
		padding: 0.75rem;
		background-color: var(--form-help-bg);
		border-left: 3px solid var(--form-help-accent);
		border-radius: var(--radius-sm);
		margin-top: 0.5rem;
		border: 1px solid var(--form-help-border);
	}

	.warning {
		padding: 0.5rem;
		background-color: var(--warning-bg);
		color: var(--warning-fg);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
		margin-top: 0.5rem;
	}

	.empty-message {
		color: var(--fg-muted);
		font-size: 0.875rem;
		font-style: italic;
		margin: 0.5rem 0;
	}
</style>
