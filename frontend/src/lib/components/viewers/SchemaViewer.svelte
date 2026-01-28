<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface Props {
		schema: Schema;
	}

	let { schema }: Props = $props();

	function getDtypeIcon(dtype: string): string {
		const lowercased = dtype.toLowerCase();
		if (lowercased.includes('int') || lowercased.includes('uint')) return '🔢';
		if (lowercased.includes('float') || lowercased.includes('decimal')) return '🔣';
		if (lowercased.includes('str') || lowercased.includes('utf8')) return '📝';
		if (lowercased.includes('bool')) return '✓';
		if (lowercased.includes('date') || lowercased.includes('time')) return '📅';
		if (lowercased.includes('list') || lowercased.includes('array')) return '📋';
		return '📊';
	}

	function getDtypeBadgeClass(dtype: string): string {
		const lowercased = dtype.toLowerCase();
		if (lowercased.includes('int') || lowercased.includes('uint')) return 'badge-numeric';
		if (lowercased.includes('float') || lowercased.includes('decimal')) return 'badge-float';
		if (lowercased.includes('str') || lowercased.includes('utf8')) return 'badge-string';
		if (lowercased.includes('bool')) return 'badge-boolean';
		if (lowercased.includes('date') || lowercased.includes('time')) return 'badge-datetime';
		return 'badge-other';
	}
</script>

<div class="schema-viewer">
	<div class="schema-header">
		<h3>Schema</h3>
		{#if schema.row_count !== null}
			<span class="row-count">{schema.row_count.toLocaleString()} rows</span>
		{/if}
	</div>

	<div class="columns-list">
		<div class="column-header-row">
			<div class="column-name">Column</div>
			<div class="column-type">Type</div>
			<div class="column-nullable">Nullable</div>
		</div>

		{#each schema.columns as column (column.name)}
			<div class="column-row">
				<div class="column-name">
					<span class="dtype-icon">{getDtypeIcon(column.dtype)}</span>
					<span class="name-text">{column.name}</span>
				</div>
				<div class="column-type">
					<span class="dtype-badge {getDtypeBadgeClass(column.dtype)}">
						{column.dtype}
					</span>
				</div>
				<div class="column-nullable">
					{#if column.nullable}
						<span class="nullable-yes">Yes</span>
					{:else}
						<span class="nullable-no">No</span>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>

<style>
	.schema-viewer {
		background: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.schema-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--border-primary);
		background: var(--panel-header-bg);
	}
	.schema-header h3 {
		margin: 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--fg-primary);
	}
	.row-count {
		font-size: 0.875rem;
		color: var(--fg-muted);
	}
	.columns-list {
		max-height: 500px;
		overflow-y: auto;
	}
	.column-header-row {
		display: grid;
		grid-template-columns: 2fr 1.5fr 1fr;
		gap: 1rem;
		padding: 0.75rem 1.25rem;
		background: var(--table-header-bg);
		border-bottom: 1px solid var(--border-primary);
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--fg-muted);
	}
	.column-row {
		display: grid;
		grid-template-columns: 2fr 1.5fr 1fr;
		gap: 1rem;
		padding: 0.875rem 1.25rem;
		border-bottom: 1px solid var(--border-primary);
		transition: background-color 0.15s ease;
	}
	.column-row:hover {
		background: var(--table-row-hover);
	}
	.column-row:last-child {
		border-bottom: none;
	}
	.column-name {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-weight: 500;
		color: var(--fg-primary);
	}
	.dtype-icon {
		font-size: 1rem;
	}
	.name-text {
		font-family: var(--font-mono);
		font-size: 0.875rem;
	}
	.column-type {
		display: flex;
		align-items: center;
	}
	.dtype-badge {
		display: inline-block;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: var(--font-semibold);
		font-family: var(--font-mono);
	}
	.badge-numeric,
	.badge-float {
		background: var(--info-bg);
		color: var(--info-fg);
	}
	.badge-string {
		background: var(--success-bg);
		color: var(--success-fg);
	}
	.badge-boolean {
		background: var(--warning-bg);
		color: var(--warning-fg);
	}
	.badge-datetime {
		background: var(--error-bg);
		color: var(--error-fg);
	}
	.badge-other {
		background: var(--bg-tertiary);
		color: var(--fg-tertiary);
	}
	.column-nullable {
		display: flex;
		align-items: center;
		font-size: 0.875rem;
	}
	.nullable-yes {
		color: var(--fg-muted);
	}
	.nullable-no {
		color: var(--fg-secondary);
		font-weight: 500;
	}
</style>
