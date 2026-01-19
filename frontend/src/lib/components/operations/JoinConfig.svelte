<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';

	interface JoinConfigData {
		how: 'inner' | 'left' | 'right' | 'outer' | 'cross';
		left_on: string | null;
		right_on: string | null;
		datasource_id: string;
		suffix: string;
	}

	interface Props {
		schema: Schema;
		config?: JoinConfigData;
	}

	let { schema, config = $bindable({ 
		how: 'inner', 
		left_on: null, 
		right_on: null, 
		datasource_id: '',
		suffix: '_right'
	}) }: Props = $props();

	let selectedDatasourceId = $state(config.datasource_id || '');
	let rightSchema = $derived.by(() => {
		if (!selectedDatasourceId) return null;
		return schemaStore.getJoinSchema(selectedDatasourceId);
	});

	$effect(() => {
		if (selectedDatasourceId && selectedDatasourceId !== config.datasource_id) {
			config.datasource_id = selectedDatasourceId;
		}
	});

	$effect(() => {
		if (config.datasource_id && !selectedDatasourceId) {
			selectedDatasourceId = config.datasource_id;
		}
	});

	const joinTypes: Array<{ value: 'inner' | 'left' | 'right' | 'outer' | 'cross'; label: string }> = [
		{ value: 'inner', label: 'Inner Join' },
		{ value: 'left', label: 'Left Join' },
		{ value: 'right', label: 'Right Join' },
		{ value: 'outer', label: 'Outer Join' },
		{ value: 'cross', label: 'Cross Join' }
	];

	const rightColumns = $derived(rightSchema?.columns ?? []);

	async function handleDatasourceChange(event: Event) {
		const target = event.target as HTMLSelectElement;
		const dsId = target.value;
		selectedDatasourceId = dsId;
		if (dsId) {
			const schemaInfo = await datasourceStore.getSchema(dsId);
			const schema: Schema = {
				columns: schemaInfo.columns.map(c => ({
					name: c.name,
					dtype: c.dtype,
					nullable: c.nullable
				})),
				row_count: schemaInfo.row_count
			};
			await schemaStore.setJoinDatasource(dsId, schema);
		}
	}
</script>

<div class="join-config">
	<h3>Join Configuration</h3>

	<div class="section">
		<h4>Right Datasource</h4>
		<select value={selectedDatasourceId} onchange={handleDatasourceChange}>
			<option value="">Select datasource...</option>
			{#each datasourceStore.datasources as ds (ds.id)}
				<option value={ds.id}>{ds.name} ({ds.source_type})</option>
			{/each}
		</select>
		{#if rightSchema}
			<div class="schema-preview">
				<strong>Right schema:</strong>
				<span class="column-count">{rightSchema.columns.length} columns</span>
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

	{#if config.how !== 'cross'}
		<div class="section">
			<h4>Join Keys</h4>

			<div class="key-inputs">
				<div class="key-input-group">
					<label for="left-key">Left Column</label>
					<select id="left-key" bind:value={config.left_on}>
						<option value={null}>Select column...</option>
						{#each schema.columns as column (column.name)}
							<option value={column.name}>{column.name} ({column.dtype})</option>
						{/each}
					</select>
				</div>

				<div class="key-input-group">
					<label for="right-key">Right Column</label>
					<select id="right-key" bind:value={config.right_on} disabled={!rightSchema}>
						<option value={null}>Select column...</option>
						{#each rightColumns as column (column.name)}
							<option value={column.name}>{column.name} ({column.dtype})</option>
						{/each}
					</select>
				</div>
			</div>

			{#if !config.left_on || !config.right_on}
				<div class="warning">Select both columns to create a join key</div>
			{/if}
		</div>
	{/if}

	<div class="section">
		<h4>Column Suffix</h4>
		<input 
			type="text" 
			bind:value={config.suffix} 
			placeholder="_right"
		/>
		<div class="help-text">
			Suffix for non-joining columns from the right dataset
		</div>
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

	.schema-preview {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: var(--panel-bg);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
	}

	.column-count {
		color: var(--fg-muted);
		margin-left: 0.5rem;
	}

	.key-inputs {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}

	.key-input-group {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.key-input-group label {
		font-size: 0.875rem;
		font-weight: 500;
		color: var(--fg-primary);
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
</style>
