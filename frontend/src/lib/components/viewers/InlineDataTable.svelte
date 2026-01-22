<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import {
		createTable,
		getCoreRowModel,
		getSortedRowModel,
		type ColumnDef,
		type SortingState,
		type HeaderGroup,
		type Row
	} from '@tanstack/table-core';
	import { previewStepData, type StepPreviewResponse } from '$lib/api/compute';
	import type { TableCellValue } from '$lib/types/api-responses';
	import { Previous } from 'runed';
	import { schemaStore } from '$lib/stores/schema.svelte';

	interface Props {
		analysisId: string;
		datasourceId: string;
		pipeline: Array<{
			id: string;
			type: string;
			config: Record<string, unknown>;
			depends_on?: string[];
		}>;
		stepId: string;
		rowLimit?: number;
	}

	type RowData = Record<string, unknown>;

	let { analysisId, datasourceId, pipeline, stepId, rowLimit = 1000 }: Props = $props();
	let currentPage = $state(1);
	let sorting = $state<SortingState>([]);
	const pipelineKey = $derived(JSON.stringify(pipeline));

	const prevPipelineKey = new Previous(() => pipelineKey);
	$effect(() => {
		if (prevPipelineKey.current !== undefined && prevPipelineKey.current !== pipelineKey) {
			currentPage = 1;
		}
	});

	const query = createQuery(() => ({
		queryKey: ['step-preview', analysisId, datasourceId, stepId, currentPage, rowLimit, pipelineKey],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const result = await previewStepData({
				analysis_id: analysisId,
				datasource_id: datasourceId,
				pipeline_steps: pipeline,
				target_step_id: stepId,
				row_limit: rowLimit,
				page: currentPage
			});
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		},
		staleTime: 30000,
		enabled: !!analysisId && !!datasourceId && !!stepId && pipeline.length > 0
	}));

	const data = $derived(query.data);
	const isLoading = $derived(query.isLoading);
	const error = $derived(query.error);

	// Update schema store with actual columns from preview
	$effect(() => {
		if (data?.columns && data.column_types) {
			schemaStore.setPreviewSchema(stepId, data.columns, data.column_types);
		}
	});

	const totalPages = $derived(data ? Math.ceil(data.total_rows / rowLimit) : 0);
	const startRow = $derived((currentPage - 1) * rowLimit + 1);
	const endRow = $derived(data ? Math.min(currentPage * rowLimit, data.total_rows) : 0);

	function formatValue(value: TableCellValue): string {
		if (value === null || value === undefined) return '—';
		if (typeof value === 'number') return value.toLocaleString();
		if (typeof value === 'boolean') return value ? 'true' : 'false';
		if (Array.isArray(value)) {
			return (
				'[' +
				value
					.map((v) => {
						if (typeof v === 'number') return v.toLocaleString();
						if (v === null || v === undefined) return 'null';
						return String(v);
					})
					.join(', ') +
				']'
			);
		}
		return String(value);
	}

	function getColumnType(col: string): string {
		return data?.column_types?.[col] || '';
	}

	function isListType(columnType: string): boolean {
		return columnType.includes('List') || columnType === 'list';
	}

	const table = $derived.by(() => {
		const currentData = data;
		if (!currentData || !currentData.columns || currentData.columns.length === 0) {
			return null;
		}

		const columnDefs: ColumnDef<RowData>[] = currentData.columns.map((col) => ({
			id: col,
			accessorKey: col,
			header: col
		}));

		return createTable({
			data: currentData.data,
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

	function nextPage() {
		if (currentPage < totalPages) currentPage++;
	}

	function prevPage() {
		if (currentPage > 1) currentPage--;
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
	}

	function getSortDirection(columnId: string): 'asc' | 'desc' | false {
		const sort = sorting.find((s: SortingState[number]) => s.id === columnId);
		if (!sort) return false;
		return sort.desc ? 'desc' : 'asc';
	}
</script>

<div class="inline-data-table">
	{#if isLoading}
		<div class="loading-overlay">
			<div class="spinner"></div>
			<p>Loading preview...</p>
		</div>
	{:else if error}
		<div class="error-state">
			<p class="error-title">Failed to load preview</p>
			<p class="error-message">{error.message}</p>
		</div>
	{:else if headerGroups.length > 0 && data}
		<div class="table-info">
			Showing {startRow.toLocaleString()}-{endRow.toLocaleString()} of {data.total_rows.toLocaleString()}
			rows
		</div>

		<div class="table-wrapper">
			<table>
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
									{#if getColumnType(header.id)}
										<span class="column-type" class:is-list={isListType(getColumnType(header.id))}>
											{getColumnType(header.id)}
										</span>
									{/if}
								</th>
							{/each}
						</tr>
					{/each}
				</thead>
				<tbody>
					{#each rows as row (row.id)}
						<tr>
							{#each row.getVisibleCells() as cell (cell.id)}
								<td class:is-list-cell={isListType(getColumnType(cell.column.id))}>
									{formatValue(cell.getValue() as TableCellValue)}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if totalPages > 1}
			<div class="pagination">
				<button onclick={prevPage} disabled={currentPage === 1}>Previous</button>
				<span class="page-info">Page {currentPage} of {totalPages}</span>
				<button onclick={nextPage} disabled={currentPage >= totalPages}>Next</button>
			</div>
		{/if}
	{:else}
		<div class="empty-state">
			<p>No data available</p>
		</div>
	{/if}
</div>

<style>
	.inline-data-table {
		width: 100%;
		background: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		overflow: hidden;
		margin: var(--space-2) 0;
		font-size: 0.875rem;
		box-shadow: var(--panel-shadow);
		user-select: text;
	}

	.loading-overlay {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 2rem;
		gap: 0.75rem;
		color: var(--fg-tertiary);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid var(--border-primary);
		border-top-color: var(--accent-primary);
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
		color: var(--fg-tertiary);
		font-size: 0.875rem;
	}

	.error-state {
		padding: 2rem;
		text-align: center;
	}

	.error-title {
		margin: 0 0 0.5rem 0;
		color: var(--error-fg);
		font-weight: 600;
	}

	.error-message {
		margin: 0;
		color: var(--fg-tertiary);
		font-size: 0.875rem;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
	}

	.empty-state p {
		margin: 0;
		color: var(--fg-muted);
		font-size: 0.875rem;
	}

	.table-info {
		padding: 0.75rem 1rem;
		font-size: 0.75rem;
		color: var(--fg-tertiary);
		background: var(--panel-header-bg);
		border-bottom: 1px solid var(--panel-border);
	}

	.table-wrapper {
		overflow-x: auto;
		max-height: 400px;
		overflow-y: auto;
		background: var(--panel-bg);
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	thead {
		position: sticky;
		top: 0;
		background: var(--table-header-bg);
		z-index: 10;
	}

	th {
		padding: 0;
		text-align: left;
		border-bottom: 2px solid var(--table-border);
		font-weight: 600;
		color: var(--fg-primary);
		font-size: 0.8125rem;
		text-transform: uppercase;
		letter-spacing: 0.02em;
	}

	.column-header {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		padding: 0.75rem 1rem;
		background: none;
		border: none;
		cursor: pointer;
		font-size: inherit;
		font-weight: inherit;
		color: inherit;
		text-transform: inherit;
		letter-spacing: inherit;
		transition: background-color 0.15s ease;
	}

	.column-header:hover {
		background: var(--bg-hover);
	}

	.column-name {
		font-family: var(--font-mono);
		font-size: 0.875rem;
	}

	.sort-indicator {
		color: var(--accent-primary);
		font-size: 0.75rem;
	}

	.column-type {
		display: inline-block;
		margin-left: 0.5rem;
		padding: 0.125rem 0.375rem;
		font-size: 0.625rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border-radius: var(--radius-sm);
		background: var(--bg-tertiary);
		color: var(--fg-muted);
		font-family: var(--font-mono);
	}

	.column-type.is-list {
		background: var(--accent-bg);
		color: var(--accent-fg);
	}

	td.is-list-cell {
		font-family: var(--font-mono);
		font-size: 0.75rem;
	}

	tbody tr {
		border-bottom: 1px solid var(--table-border);
		transition: background-color 0.15s ease;
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
		padding: 0.75rem 1rem;
		color: var(--fg-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 250px;
		font-size: 0.8125rem;
		user-select: text;
	}

	.pagination {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem 1rem;
		background: var(--panel-header-bg);
		border-top: 1px solid var(--panel-border);
	}

	.pagination button {
		padding: 0.5rem 1rem;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background: var(--panel-bg);
		color: var(--fg-primary);
		font-size: 0.875rem;
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.pagination button:hover:not(:disabled) {
		background: var(--bg-hover);
		border-color: var(--border-secondary);
	}

	.pagination button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.page-info {
		font-size: 0.75rem;
		color: var(--fg-tertiary);
	}
</style>
