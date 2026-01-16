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
		border: 1px solid #ddd;
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.5rem;
		font-size: 1rem;
	}

	.help-banner {
		background-color: #e7f3ff;
		padding: 0.75rem;
		border-left: 3px solid #007bff;
		border-radius: 4px;
		margin-bottom: 1rem;
		font-size: 0.875rem;
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: #f8f9fa;
		border-radius: 4px;
	}

	.help-text {
		font-size: 0.875rem;
		color: #6c757d;
		margin-bottom: 0.75rem;
	}

	.warning-box {
		padding: 1rem;
		background-color: #fff3cd;
		border-left: 3px solid #ffc107;
		border-radius: 4px;
	}

	.warning-box strong {
		display: block;
		margin-bottom: 0.5rem;
		color: #856404;
	}

	.warning-box p {
		margin: 0;
		font-size: 0.875rem;
		color: #856404;
	}

	.column-list {
		max-height: 200px;
		overflow-y: auto;
		border: 1px solid #ddd;
		border-radius: 4px;
		padding: 0.5rem;
		background-color: white;
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: 0.5rem;
		cursor: pointer;
		border-radius: 4px;
	}

	.column-item:hover {
		background-color: #f8f9fa;
	}

	.column-item input[type='checkbox'] {
		margin-right: 0.5rem;
		cursor: pointer;
	}

	.selected-info {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: #e7f3ff;
		border-radius: 4px;
		font-size: 0.875rem;
	}

	.info-box {
		margin-bottom: 1rem;
		padding: 0.75rem;
		background-color: #d4edda;
		border-left: 3px solid #28a745;
		border-radius: 4px;
		font-size: 0.875rem;
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
		background-color: #fff3cd;
		border-left: 3px solid #ffc107;
		border-radius: 4px;
		font-size: 0.875rem;
	}
</style>
