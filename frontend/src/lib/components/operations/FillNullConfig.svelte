<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface FillNullConfigData {
		strategy: string;
		columns: string[] | null;
		value?: string | number;
		value_type?: string;
	}

	interface Props {
		schema: Schema;
		config?: FillNullConfigData;
	}

	let {
		schema,
		config = $bindable({ strategy: 'literal', columns: null, value: '', value_type: 'Utf8' })
	}: Props = $props();

	const strategies = [
		{ value: 'literal', label: 'Fill with Value', needsValue: true, needsColumns: true },
		{ value: 'forward', label: 'Forward Fill', needsValue: false, needsColumns: true },
		{ value: 'backward', label: 'Backward Fill', needsValue: false, needsColumns: true },
		{ value: 'mean', label: 'Fill with Mean', needsValue: false, needsColumns: true },
		{ value: 'median', label: 'Fill with Median', needsValue: false, needsColumns: true },
		{ value: 'drop_rows', label: 'Drop Rows with Nulls', needsValue: false, needsColumns: true }
	];

	const currentStrategy = $derived(strategies.find((s) => s.value === config.strategy));

	function toggleColumn(columnName: string) {
		const base = config.columns ?? [];
		const index = base.indexOf(columnName);
		if (index > -1) {
			config.columns = base.filter((_, i) => i !== index);
		} else {
			config.columns = [...base, columnName];
		}
	}

	function selectAllColumns() {
		config.columns = schema.columns.map((c) => c.name);
	}

	function deselectAllColumns() {
		config.columns = [];
	}
</script>

<div class="fill-null-config">
	<h3>Fill Null Configuration</h3>

	<div class="section">
		<h4>Fill Strategy</h4>
		<select id="fill-strategy" bind:value={config.strategy}>
			{#each strategies as strategy (strategy.value)}
				<option value={strategy.value}>{strategy.label}</option>
			{/each}
		</select>
	</div>

	{#if currentStrategy?.needsValue}
		<div class="section">
			<h4>Fill Value</h4>
			<input id="fill-value" type="text" bind:value={config.value} placeholder="Enter value (e.g., 0, N/A)" />
			<select id="fill-value-type" bind:value={config.value_type}>
				<option value="Utf8">String</option>
				<option value="Int64">Integer</option>
				<option value="Float64">Float</option>
				<option value="Boolean">Boolean</option>
				<option value="Date">Date</option>
				<option value="Datetime">Datetime</option>
				<option value="Unknown">Unknown</option>
			</select>
		</div>
	{/if}

	<div class="section">
		<h4>Target Columns</h4>
		<div class="column-actions">
			<button type="button" onclick={selectAllColumns} class="action-btn">Select All</button>
			<button type="button" onclick={deselectAllColumns} class="action-btn">Deselect All</button>
		</div>

		<div class="column-list">
			{#each schema.columns as column (column.name)}
				<label class="column-item">
					<input
						type="checkbox"
						checked={config.columns?.includes(column.name) || false}
						onchange={() => toggleColumn(column.name)}
					/>
					<span>{column.name} ({column.dtype})</span>
				</label>
			{/each}
		</div>

		{#if config.columns && config.columns.length > 0}
			<div class="selected-info">
				Selected {config.columns.length} column{config.columns.length !== 1 ? 's' : ''}:
				{config.columns.join(', ')}
			</div>
		{:else}
			<div class="selected-info">No columns selected - will apply to all columns</div>
		{/if}
	</div>
</div>

<style>
	.fill-null-config {
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
		margin-bottom: 0.5rem;
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

	select,
	input[type='text'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.column-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
		flex-wrap: wrap;
	}

	.action-btn {
		padding: 0.25rem 0.75rem;
		background-color: var(--bg-tertiary);
		color: var(--fg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.875rem;
	}

	.action-btn:hover {
		background-color: var(--bg-hover);
	}

	.column-list {
		max-height: 200px;
		overflow-y: auto;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: 0.5rem;
		background-color: var(--bg-primary);
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: 0.5rem;
		cursor: pointer;
		border-radius: var(--radius-sm);
	}

	.column-item:hover {
		background-color: var(--bg-hover);
	}

	.column-item input[type='checkbox'] {
		margin-right: 0.5rem;
		cursor: pointer;
	}

	.selected-info {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: var(--info-bg);
		border: 1px solid var(--info-border);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
		color: var(--info-fg);
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
