<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface DeduplicateConfigData {
		subset: string[] | null;
		keep: string;
	}

	interface Props {
		schema: Schema;
		config?: DeduplicateConfigData;
	}

	let { schema, config = $bindable({ subset: null, keep: 'first' }) }: Props = $props();

	const keepStrategies = [
		{ value: 'first', label: 'Keep First' },
		{ value: 'last', label: 'Keep Last' },
		{ value: 'none', label: 'Keep None' }
	];

	function toggleColumn(columnName: string) {
		const base = config.subset ?? [];
		const index = base.indexOf(columnName);
		if (index > -1) {
			config.subset = base.filter((_, i) => i !== index);
		} else {
			config.subset = [...base, columnName];
		}
	}

	function selectAllColumns() {
		config.subset = schema.columns.map((c) => c.name);
	}

	function deselectAllColumns() {
		config.subset = [];
	}
</script>

<div class="deduplicate-config">
	<h3>Deduplicate Configuration</h3>

	<div class="section">
		<h4>Keep Strategy</h4>
		<div class="strategy-grid">
			{#each keepStrategies as strategy (strategy.value)}
				<label class="strategy-option">
					<input type="radio" name="keep-strategy" bind:group={config.keep} value={strategy.value} />
					<span>{strategy.label}</span>
				</label>
			{/each}
		</div>
	</div>

	<div class="section">
		<h4>Column Subset</h4>

		<div class="column-actions">
			<button type="button" onclick={selectAllColumns} class="action-btn">Select All</button>
			<button type="button" onclick={deselectAllColumns} class="action-btn">Deselect All</button>
		</div>

		<div class="column-list">
			{#each schema.columns as column (column.name)}
				<label class="column-item">
					<input
						type="checkbox"
						checked={config.subset?.includes(column.name) || false}
						onchange={() => toggleColumn(column.name)}
					/>
					<span>{column.name} ({column.dtype})</span>
				</label>
			{/each}
		</div>

		{#if config.subset && config.subset.length > 0}
			<div class="selected-info">
				Checking {config.subset.length} column{config.subset.length !== 1 ? 's' : ''}:
				{config.subset.join(', ')}
			</div>
		{:else}
			<div class="selected-info">No columns selected - will check all columns for duplicates</div>
		{/if}
	</div>
</div>

<style>
	.deduplicate-config {
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

	.strategy-grid {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.strategy-option {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.75rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all 0.2s;
	}

	.strategy-option:hover {
		border-color: var(--border-focus);
		background-color: var(--bg-hover);
	}

	.strategy-option input[type='radio'] {
		margin-right: 0.5rem;
		cursor: pointer;
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
