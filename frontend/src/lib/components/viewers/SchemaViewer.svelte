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
		background: #fff;
		border: 1px solid #e5e7eb;
		border-radius: 8px;
		overflow: hidden;
	}

	.schema-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid #e5e7eb;
		background: #f9fafb;
	}

	.schema-header h3 {
		margin: 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: #111827;
	}

	.row-count {
		font-size: 0.875rem;
		color: #6b7280;
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
		background: #f3f4f6;
		border-bottom: 1px solid #e5e7eb;
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #6b7280;
	}

	.column-row {
		display: grid;
		grid-template-columns: 2fr 1.5fr 1fr;
		gap: 1rem;
		padding: 0.875rem 1.25rem;
		border-bottom: 1px solid #f3f4f6;
		transition: background-color 0.15s ease;
	}

	.column-row:hover {
		background: #f9fafb;
	}

	.column-row:last-child {
		border-bottom: none;
	}

	.column-name {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-weight: 500;
		color: #111827;
	}

	.dtype-icon {
		font-size: 1rem;
	}

	.name-text {
		font-family: 'Courier New', monospace;
		font-size: 0.875rem;
	}

	.column-type {
		display: flex;
		align-items: center;
	}

	.dtype-badge {
		display: inline-block;
		padding: 0.25rem 0.625rem;
		border-radius: 4px;
		font-size: 0.75rem;
		font-weight: 600;
		font-family: 'Courier New', monospace;
	}

	.badge-numeric {
		background: #dbeafe;
		color: #1e40af;
	}

	.badge-float {
		background: #e0e7ff;
		color: #4338ca;
	}

	.badge-string {
		background: #dcfce7;
		color: #15803d;
	}

	.badge-boolean {
		background: #fef3c7;
		color: #92400e;
	}

	.badge-datetime {
		background: #fce7f3;
		color: #9f1239;
	}

	.badge-other {
		background: #f3f4f6;
		color: #374151;
	}

	.column-nullable {
		display: flex;
		align-items: center;
		font-size: 0.875rem;
	}

	.nullable-yes {
		color: #6b7280;
	}

	.nullable-no {
		color: #374151;
		font-weight: 500;
	}
</style>
