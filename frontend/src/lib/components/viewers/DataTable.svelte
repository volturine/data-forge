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

	import { formatDateTimeDisplay, formatDateDisplay } from '$lib/utils/datetime';

	interface Props {
		columns: string[];
		data: Record<string, unknown>[];
		columnTypes?: Record<string, string>;
		loading?: boolean;
		onSort?: (column: string, direction: 'asc' | 'desc') => void;
	}

	type RowData = Record<string, unknown>;

	let { columns, data, columnTypes = {}, loading = false, onSort }: Props = $props();

	let sorting = $state<SortingState>([]);

	const table = $derived.by(() => {
		if (data.length === 0 || columns.length === 0) return null;

		const columnDefs: ColumnDef<RowData>[] = columns.map((col) => ({
			id: col,
			accessorKey: col,
			header: col
		}));

		return createTable({
			data,
			columns: columnDefs,
			state: {
				sorting,
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
	});

	const headerGroups = $derived<HeaderGroup<RowData>[]>(table ? table.getHeaderGroups() : []);
	const rows = $derived<Row<RowData>[]>(table ? table.getRowModel().rows : []);

	function getTemporalType(dtype: string | undefined): 'date' | 'datetime' | null {
		if (!dtype) return null;
		const lower = dtype.toLowerCase();
		if (lower.includes('datetime')) return 'datetime';
		if (lower.includes('date')) return 'date';
		if (lower.includes('time')) return 'datetime';
		return null;
	}

	function formatValue(value: TableCellValue, columnId: string): string {
		if (value === null || value === undefined) return '—';
		const temporal = getTemporalType(columnTypes[columnId]);
		if (temporal === 'date') return formatDateDisplay(value as string);
		if (temporal === 'datetime') return formatDateTimeDisplay(value as string);
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

<div class="relative overflow-hidden rounded-md border bg-panel border-panel" style="box-shadow: var(--panel-shadow);">
	{#if loading}
		<div class="flex flex-col items-center justify-center gap-4 p-12 pointer-events-none text-fg-tertiary">
			<div class="spinner"></div>
			<p class="text-sm m-0 text-fg-tertiary">Loading data...</p>
		</div>
	{/if}

	{#if !loading && data.length === 0}
		<div class="p-12 text-center m-0 text-fg-muted">
			<p class="m-0">No data available</p>
		</div>
	{:else if headerGroups.length > 0}
		<div class="overflow-x-auto overflow-y-auto max-h-[600px] bg-panel">
			<table class="w-full border-collapse text-sm">
				<thead class="sticky top-0 z-50" style="background: var(--table-header-bg);">
					{#each headerGroups as headerGroup (headerGroup.id)}
						<tr>
							{#each headerGroup.headers as header (header.id)}
								<th class="p-0 text-left font-semibold border-b-2 border-table">
									<button
										class="flex items-center justify-between w-full px-4 py-3 bg-transparent border-none cursor-pointer text-sm font-semibold transition-colors text-fg-primary hover:bg-hover"
										onclick={() => toggleSort(header.id)}
									>
										<span class="font-mono">
											{typeof header.column.columnDef.header === 'string'
												? header.column.columnDef.header
												: header.id}
										</span>
										{#if getSortDirection(header.id)}
											<span class="ml-2 text-base text-accent">
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
						<tr class="border-b transition-colors last:border-b-0 border-table even:bg-secondary hover:!bg-hover">
							{#each row.getVisibleCells() as cell (cell.id)}
								<td class="px-4 py-3 whitespace-nowrap overflow-hidden text-ellipsis max-w-[300px] text-sm text-fg-secondary">
									{formatValue(cell.getValue() as TableCellValue, cell.column.id)}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if !loading && data.length > 0}
		<div class="px-4 py-3 border-t border-panel" style="background: var(--panel-header-bg);">
			<span class="text-xs text-fg-tertiary">
				Showing {data.length.toLocaleString()} row{data.length !== 1 ? 's' : ''}
			</span>
		</div>
	{/if}
</div>
