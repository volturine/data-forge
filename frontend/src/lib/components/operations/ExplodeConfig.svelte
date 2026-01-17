<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface ExplodeConfigData {
		columns: string[];
	}

	interface Props {
		schema: Schema;
		config?: ExplodeConfigData;
	}

	let { schema, config = $bindable({ columns: [] }) }: Props = $props();

	const listColumns = $derived(
		schema.columns.filter(
			(col) =>
				col.dtype.toLowerCase().includes('list') ||
				col.dtype.toLowerCase().includes('array') ||
				col.dtype.toLowerCase().startsWith('list[')
		)
	);

	function toggleColumn(columnName: string) {
		const index = config.columns.indexOf(columnName);
		if (index > -1) {
			config.columns.splice(index, 1);
		} else {
			config.columns.push(columnName);
		}
	}
</script>

<div class="explode-config">
	<h3>Explode Configuration</h3>

	<div class="help-banner">
		Transform list/array columns into multiple rows. Each list element becomes a separate row,
		duplicating all other column values.
	</div>

	<div class="section">
		<h4>Columns to Explode</h4>
		<p class="help-text">Select one or more list/array columns to explode</p>

		{#if listColumns.length === 0}
			<div class="warning-box">
				<strong>No list/array columns detected</strong>
				<p>
					This operation requires columns with list or array types. Your current schema doesn't have
					any.
				</p>
			</div>
		{:else}
			<div class="column-list">
				{#each listColumns as column (column.name)}
					<label class="column-item">
						<input
							type="checkbox"
							checked={config.columns.includes(column.name)}
							onchange={() => toggleColumn(column.name)}
						/>
						<span>{column.name} ({column.dtype})</span>
					</label>
				{/each}
			</div>

			{#if config.columns.length > 0}
				<div class="selected-info">
					Selected {config.columns.length} column{config.columns.length !== 1 ? 's' : ''}:
					{config.columns.join(', ')}
				</div>
			{/if}
		{/if}
	</div>

	<div class="info-box">
		<strong>How it works:</strong>
		<ul>
			<li>Each list element becomes a new row</li>
			<li>Other column values are duplicated for each new row</li>
			<li>Null values in lists are preserved as null rows</li>
			<li>Empty lists create no additional rows</li>
		</ul>
	</div>

	<div class="example">
		<strong>Example:</strong> A row with tags=['python', 'data', 'ai'] becomes 3 rows, each with one tag
		value.
	</div>
</div>

<style>
	.explode-config {
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

	.help-banner {
		background-color: var(--info-bg);
		padding: 0.75rem;
		border-left: 3px solid var(--info-border);
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
		font-size: 0.875rem;
		color: var(--info-fg);
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: var(--form-section-bg);
		border-radius: var(--radius-md);
		border: 1px solid var(--form-section-border);
	}

	.help-text {
		font-size: 0.875rem;
		color: var(--fg-tertiary);
		margin-bottom: 0.75rem;
	}

	.warning-box {
		padding: 1rem;
		background-color: var(--warning-bg);
		border-left: 3px solid var(--warning-border);
		border-radius: var(--radius-sm);
		color: var(--warning-fg);
	}

	.warning-box strong {
		display: block;
		margin-bottom: 0.5rem;
		color: inherit;
	}

	.warning-box p {
		margin: 0;
		font-size: 0.875rem;
		color: inherit;
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

	.info-box {
		margin-bottom: 1rem;
		padding: 0.75rem;
		background-color: var(--success-bg);
		border-left: 3px solid var(--success-border);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
		color: var(--success-fg);
	}

	.info-box strong {
		display: block;
		margin-bottom: 0.5rem;
	}

	.info-box ul {
		margin: 0;
		padding-left: 1.5rem;
	}

	.info-box li {
		margin-bottom: 0.25rem;
	}

	.example {
		margin-bottom: 1rem;
		padding: 0.75rem;
		background-color: var(--warning-bg);
		border-left: 3px solid var(--warning-border);
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
		color: var(--warning-fg);
	}
</style>
