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

	// Safe accessor
	let safeColumns = $derived(Array.isArray(config?.columns) ? config.columns : []);

	const listColumns = $derived(
		schema.columns.filter(
			(col) =>
				col.dtype.toLowerCase().includes('list') ||
				col.dtype.toLowerCase().includes('array') ||
				col.dtype.toLowerCase().startsWith('list[')
		)
	);

	function toggleColumn(columnName: string) {
		const cols = safeColumns;
		const index = cols.indexOf(columnName);
		if (index > -1) {
			config.columns = cols.filter((_, i) => i !== index);
		} else {
			config.columns = [...cols, columnName];
		}
	}
</script>

<div class="config-panel">
	<h3>Explode Configuration</h3>

	<div class="help-banner">
		Transform list/array columns into multiple rows. Each list element becomes a separate row,
		duplicating all other column values.
	</div>

	<div class="form-section">
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
							checked={safeColumns.includes(column.name)}
							onchange={() => toggleColumn(column.name)}
						/>
						<span class="column-name">{column.name}</span>
						<span class="column-type">{column.dtype}</span>
					</label>
				{/each}
			</div>

			{#if safeColumns.length > 0}
				<div class="info-box">
					Selected {safeColumns.length} column{safeColumns.length !== 1 ? 's' : ''}:
					{safeColumns.join(', ')}
				</div>
			{/if}
		{/if}
	</div>

	<div class="success-box">
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
	.help-banner {
		background-color: var(--info-bg);
		padding: var(--space-3);
		border-left: 3px solid var(--info-border);
		border-radius: var(--radius-sm);
		margin-bottom: var(--space-4);
		font-size: var(--text-sm);
		color: var(--info-fg);
	}
	.help-text {
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
		margin-bottom: var(--space-3);
	}
	.warning-box strong {
		display: block;
		margin-bottom: var(--space-2);
	}
	.warning-box p {
		margin: 0;
		font-size: var(--text-sm);
	}
	.success-box ul {
		margin: 0;
		padding-left: var(--space-6);
	}
	.success-box li {
		margin-bottom: var(--space-1);
	}
	.example {
		margin-bottom: var(--space-4);
		padding: var(--space-3);
		background-color: var(--warning-bg);
		border-left: 3px solid var(--warning-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
		color: var(--warning-fg);
	}
</style>
