<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { JoinConfigData } from '$lib/types/operation-config';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';

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

	const currentTabDatasource = $derived(analysisStore.activeTab?.datasource_id);
	const datasourceOptions = $derived.by(() => datasourceStore.datasources);
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
			<div id="join-schema-preview" class="schema-preview" aria-live="polite">
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
		<div id="join-type-help" class="help-text" aria-describedby="join-type-help">
			<strong>Inner:</strong> Only matching rows from both.<br />
			<strong>Left:</strong> All left rows, matching right rows.<br />
			<strong>Right:</strong> All right rows, matching left rows.<br />
			<strong>Outer:</strong> All rows from both.<br />
			<strong>Cross:</strong> Cartesian product (no keys needed).
		</div>
	</div>

	{#if !isCrossJoin}
		<div class="form-section" role="group" aria-labelledby="join-columns-heading">
			<div class="section-header">
				<h4 id="join-columns-heading">Join Columns</h4>
				<button
					id="join-btn-add-column"
					data-testid="join-add-column-button"
					type="button"
					class="btn-add"
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
				<div class="join-column-row" role="group" aria-label={`Join column pair ${_index + 1}`}>
					<div class="column-dropdown-wrapper">
						<label for={`join-left-${joinCol.id}`}>Left Column</label>
						<ColumnDropdown
							{schema}
							value={joinCol.left_column ?? ''}
							onChange={(val) => (joinCol.left_column = val)}
							placeholder="Select..."
						/>
					</div>
					<div class="column-dropdown-wrapper">
						<label for={`join-right-${joinCol.id}`}>Right Column</label>
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
						class="btn-remove"
						onclick={() => removeJoinColumn(joinCol.id)}
						aria-label={`Remove join column pair ${_index + 1}`}
					>
						✕
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
		<div class="section-header">
			<h4 id="right-columns-heading">Columns from Right Dataset</h4>
			<div class="bulk-actions">
				<button
					id="join-btn-select-all-right"
					data-testid="join-select-all-right-button"
					type="button"
					class="btn-link"
					onclick={selectAllRightColumns}
					aria-label="Select all right columns"
				>
					Select All
				</button>
				<button
					id="join-btn-deselect-all-right"
					data-testid="join-deselect-all-right-button"
					type="button"
					class="btn-link"
					onclick={deselectAllRightColumns}
					aria-label="Deselect all right columns"
				>
					Deselect All
				</button>
			</div>
		</div>

		{#if rightColumns.length === 0}
			<p id="join-right-columns-empty" class="empty-message">Select a right datasource first</p>
		{:else}
			<div
				id="join-right-columns-list"
				class="column-list"
				role="group"
				aria-label="Right dataset columns"
			>
				{#each rightColumns as col (col.name)}
					<label class="column-checkbox">
						<input
							id={`join-checkbox-${col.name}`}
							data-testid={`join-right-column-checkbox-${col.name}`}
							type="checkbox"
							checked={(config.right_columns ?? []).includes(col.name)}
							onchange={() => toggleRightColumn(col.name)}
							aria-label={`Include column ${col.name} from right dataset`}
						/>
						<span>{col.name}</span>
						<ColumnTypeBadge columnType={col.dtype} size="xs" />
					</label>
				{/each}
			</div>
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
		<div id="join-suffix-hint" class="help-text">
			Suffix for columns from the right dataset (when names collide)
		</div>
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

	.form-section select,
	.form-section input {
		width: 100%;
		margin-bottom: var(--space-2);
	}

	.join-column-row {
		display: flex;
		gap: var(--space-2);
		align-items: flex-end;
		margin-bottom: var(--space-3);
		padding: var(--space-3);
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
	}

	.column-dropdown-wrapper {
		flex: 1;
	}
	.column-dropdown-wrapper label {
		display: block;
		font-size: var(--text-xs);
		margin-bottom: var(--space-1);
		color: var(--fg-muted);
	}

	.btn-add {
		padding: var(--space-1) var(--space-3);
		background-color: var(--primary-bg);
		color: var(--primary-fg);
		border: none;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: var(--text-sm);
	}
	.btn-add:hover {
		background-color: var(--primary-hover);
	}

	.btn-remove {
		padding: var(--space-2);
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
		color: var(--accent-primary);
		cursor: pointer;
		font-size: var(--text-xs);
		padding: var(--space-1);
		text-decoration: underline;
	}

	.column-list {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: var(--space-2);
	}
	.column-checkbox {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.column-checkbox input {
		margin: 0;
		width: auto;
	}

	.schema-preview {
		margin-top: var(--space-2);
		padding: var(--space-2);
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
	}

	.help-text {
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
		line-height: 1.5;
		padding: var(--space-3);
		background-color: var(--form-help-bg);
		border-left: 3px solid var(--form-help-accent);
		border-radius: var(--radius-sm);
		margin-top: var(--space-2);
		border: 1px solid var(--form-help-border);
	}

	.empty-message {
		color: var(--fg-muted);
		font-style: italic;
		margin: var(--space-2) 0;
	}
</style>
