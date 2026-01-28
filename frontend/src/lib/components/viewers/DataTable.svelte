<script lang="ts">
	import {
		createTable,
		getCoreRowModel,
		getSortedRowModel,
		type ColumnDef,
		type SortingState,
		type HeaderGroup,
		type Row
	} from '@tanstack/table-core';
	import type { TableCellValue } from '$lib/types/api-responses';

	interface Props {
		columns: string[];
		data: Record<string, unknown>[];
		loading?: boolean;
		onSort?: (column: string, direction: 'asc' | 'desc') => void;
	}

	type RowData = Record<string, unknown>;

	let { columns, data, loading = false, onSort }: Props = $props();

	let sorting = $state<SortingState>([]);
	let headerGroups = $state<HeaderGroup<RowData>[]>([]);
	let rows = $state<Row<RowData>[]>([]);

	// Single effect that handles table creation and updates
	$effect(() => {
		// Dependencies: data, columns, sorting
		const currentData = data;
		const currentColumns = columns;
		const currentSorting = sorting;

		if (currentData.length === 0 || currentColumns.length === 0) {
			headerGroups = [];
			rows = [];
			return;
		}

		const columnDefs: ColumnDef<RowData>[] = currentColumns.map((col) => ({
			id: col,
			accessorKey: col,
			header: col
		}));

		const table = createTable({
			data: currentData,
			columns: columnDefs,
			state: {
				sorting: currentSorting,
				columnPinning: { left: [], right: [] },
				columnVisibility: {},
				expanded: {},
				grouping: [],
				rowSelection: {},
				columnOrder: []
			},
			onSortingChange: () => {},
			getCoreRowModel: getCoreRowModel(),
			getSortedRowModel: getSortedRowModel(),
			onStateChange: () => {},
			renderFallbackValue: null
		});

		headerGroups = table.getHeaderGroups();
		rows = table.getRowModel().rows;
	});

	function formatValue(value: TableCellValue): string {
		if (value === null || value === undefined) return '—';
		if (typeof value === 'number') return value.toLocaleString();
		if (typeof value === 'boolean') return value ? 'true' : 'false';
		return String(value);
	}

	function toggleSort(columnId: string) {
		const existing = sorting.find((s: SortingState[number]) => s.id === columnId);
		if (!existing) {
			sorting = [{ id: columnId, desc: false }];
		} else if (!existing.desc) {
			sorting = [{ id: columnId, desc: true }];
		} else {
			sorting = [];
		}

		if (onSort && sorting.length > 0) {
			onSort(sorting[0].id, sorting[0].desc ? 'desc' : 'asc');
		}
	}

	function getSortDirection(columnId: string): 'asc' | 'desc' | false {
		const sort = sorting.find((s: SortingState[number]) => s.id === columnId);
		if (!sort) return false;
		return sort.desc ? 'desc' : 'asc';
	}
</script>

<div class="data-table-container">
	{#if loading}
		<div class="loading-overlay">
			<div class="spinner"></div>
			<p class="text-tertiary text-sm">Loading data...</p>
		</div>
	{/if}

	{#if !loading && data.length === 0}
		<div class="empty-state">
			<p>No data available</p>
		</div>
	{:else if headerGroups.length > 0}
		<div class="table-wrapper">
			<table class="data-table">
				<thead>
					{#each headerGroups as headerGroup (headerGroup.id)}
						<tr>
							{#each headerGroup.headers as header (header.id)}
								<th>
									<button class="column-header" onclick={() => toggleSort(header.id)}>
										<span class="column-name">
											{typeof header.column.columnDef.header === 'string'
												? header.column.columnDef.header
												: header.id}
										</span>
										{#if getSortDirection(header.id)}
											<span class="sort-indicator">
												{getSortDirection(header.id) === 'asc' ? '↑' : '↓'}
											</span>
										{/if}
									</button>
								</th>
							{/each}
						</tr>
					{/each}
				</thead>
				<tbody>
					{#each rows as row (row.id)}
						<tr>
							{#each row.getVisibleCells() as cell (cell.id)}
								<td>
									{formatValue(cell.getValue() as TableCellValue)}
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
		background: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		overflow: hidden;
		box-shadow: var(--panel-shadow);
	}
	.loading-overlay {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: var(--space-12);
		gap: var(--space-4);
		color: var(--fg-tertiary);
	}
	.loading-overlay p {
		margin: 0;
	}
	.empty-state {
		padding: var(--space-12);
		text-align: center;
		color: var(--fg-muted);
	}
	.empty-state p {
		margin: 0;
	}
	.table-wrapper {
		overflow-x: auto;
		max-height: 600px;
		overflow-y: auto;
		background: var(--panel-bg);
	}
	.data-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	thead {
		position: sticky;
		top: 0;
		background: var(--table-header-bg);
		z-index: var(--z-dropdown);
	}
	th {
		padding: 0;
		border-bottom: 2px solid var(--table-border);
		font-weight: var(--font-semibold);
		text-align: left;
	}
	.column-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--space-3) var(--space-4);
		background: none;
		border: none;
		cursor: pointer;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-primary);
		transition: background-color var(--transition);
	}
	.column-header:hover {
		background: var(--bg-hover);
	}
	.column-name {
		font-family: var(--font-mono);
	}
	.sort-indicator {
		margin-left: var(--space-2);
		color: var(--accent-primary);
		font-size: var(--text-base);
	}
	tbody tr {
		border-bottom: 1px solid var(--table-border);
		transition: background-color var(--transition);
	}
	tbody tr:nth-child(even) {
		background: var(--table-row-alt);
	}
	tbody tr:hover {
		background: var(--table-row-hover);
	}
	tbody tr:last-child {
		border-bottom: none;
	}
	td {
		padding: var(--space-3) var(--space-4);
		color: var(--fg-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 300px;
		font-size: var(--text-sm);
	}
	.table-footer {
		padding: var(--space-3) var(--space-4);
		border-top: 1px solid var(--panel-border);
		background: var(--panel-header-bg);
	}
	.row-info {
		font-size: var(--text-xs);
		color: var(--fg-tertiary);
	}
</style>
