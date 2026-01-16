<script lang="ts">
	import type { TableCellValue } from '$lib/types/api-responses';

	interface Props {
		columns: string[];
		data: Record<string, unknown>[];
		loading?: boolean;
		onSort?: (column: string, direction: 'asc' | 'desc') => void;
	}

	let { columns, data, loading = false, onSort }: Props = $props();

	let sortColumn = $state<string | null>(null);
	let sortDirection = $state<'asc' | 'desc'>('asc');

	let sortedData = $derived(() => {
		if (!sortColumn) return data;

		const col = sortColumn;
		const sorted = [...data].sort((a, b) => {
			const aVal = a[col];
			const bVal = b[col];

			if (aVal === null || aVal === undefined) return 1;
			if (bVal === null || bVal === undefined) return -1;

			if (typeof aVal === 'number' && typeof bVal === 'number') {
				return sortDirection === 'asc' ? aVal - bVal : bVal - aVal;
			}

			const aStr = String(aVal);
			const bStr = String(bVal);
			const comparison = aStr.localeCompare(bStr);
			return sortDirection === 'asc' ? comparison : -comparison;
		});

		return sorted;
	});

	function handleSort(column: string) {
		if (sortColumn === column) {
			sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
		} else {
			sortColumn = column;
			sortDirection = 'asc';
		}

		if (onSort) {
			onSort(column, sortDirection);
		}
	}

	function formatValue(value: TableCellValue): string {
		if (value === null || value === undefined) return '—';
		if (typeof value === 'number') {
			return value.toLocaleString();
		}
		if (typeof value === 'boolean') {
			return value ? 'true' : 'false';
		}
		return String(value);
	}
</script>

<div class="data-table-container">
	{#if loading}
		<div class="loading-overlay">
			<div class="spinner"></div>
			<p>Loading data...</p>
		</div>
	{/if}

	{#if !loading && data.length === 0}
		<div class="empty-state">
			<p>No data available</p>
		</div>
	{:else}
		<div class="table-wrapper">
			<table class="data-table">
				<thead>
					<tr>
						{#each columns as column (column)}
							<th>
								<button class="column-header" onclick={() => handleSort(column)}>
									<span class="column-name">{column}</span>
									{#if sortColumn === column}
										<span class="sort-indicator">
											{sortDirection === 'asc' ? '↑' : '↓'}
										</span>
									{/if}
								</button>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each sortedData() as row, _rowIndex (_rowIndex)}
						<tr>
							{#each columns as column (column)}
								<td>
									{formatValue(row[column] as TableCellValue)}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if !loading && data.length > 0}
		<div class="table-footer">
			<span class="row-info">
				Showing {data.length.toLocaleString()} row{data.length !== 1 ? 's' : ''}
			</span>
		</div>
	{/if}
</div>

<style>
	.data-table-container {
		position: relative;
		background: #fff;
		border: 1px solid #e5e7eb;
		border-radius: 8px;
		overflow: hidden;
	}

	.loading-overlay {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 3rem;
		gap: 1rem;
	}

	.spinner {
		width: 40px;
		height: 40px;
		border: 4px solid #f3f4f6;
		border-top-color: #3b82f6;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.loading-overlay p {
		margin: 0;
		color: #6b7280;
		font-size: 0.875rem;
	}

	.empty-state {
		padding: 3rem;
		text-align: center;
	}

	.empty-state p {
		margin: 0;
		color: #9ca3af;
		font-size: 0.875rem;
	}

	.table-wrapper {
		overflow-x: auto;
		max-height: 600px;
		overflow-y: auto;
	}

	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.875rem;
	}

	thead {
		position: sticky;
		top: 0;
		background: #f9fafb;
		z-index: 10;
	}

	th {
		padding: 0;
		border-bottom: 2px solid #e5e7eb;
		font-weight: 600;
		text-align: left;
	}

	.column-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 0.75rem 1rem;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 0.875rem;
		font-weight: 600;
		color: #374151;
		transition: background-color 0.15s ease;
	}

	.column-header:hover {
		background: #f3f4f6;
	}

	.column-name {
		font-family: 'Courier New', monospace;
	}

	.sort-indicator {
		margin-left: 0.5rem;
		color: #3b82f6;
		font-size: 1rem;
	}

	tbody tr {
		border-bottom: 1px solid #f3f4f6;
		transition: background-color 0.15s ease;
	}

	tbody tr:hover {
		background: #f9fafb;
	}

	tbody tr:last-child {
		border-bottom: none;
	}

	td {
		padding: 0.75rem 1rem;
		color: #111827;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
	}

	.table-footer {
		padding: 0.75rem 1rem;
		border-top: 1px solid #e5e7eb;
		background: #f9fafb;
	}

	.row-info {
		font-size: 0.75rem;
		color: #6b7280;
	}
</style>
