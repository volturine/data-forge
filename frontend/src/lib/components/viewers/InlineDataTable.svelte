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
	import { applySteps } from '$lib/utils/pipeline';
	import type { TableCellValue } from '$lib/types/api-responses';
	import { Previous } from 'runed';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { formatDateTimeDisplay, formatDateDisplay } from '$lib/utils/datetime';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import { resolveColumnType } from '$lib/utils/columnTypes';

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

	let activePipeline = $derived(applySteps(pipeline));
	let isActiveStep = $derived(activePipeline.some((step) => step.id === stepId));

	const pipelineKey = $derived(JSON.stringify(activePipeline));

	const query = createQuery(() => {
		return {
			queryKey: [
				'step-preview',
				analysisId,
				datasourceId,
				stepId,
				currentPage,
				rowLimit,
				pipelineKey
			],
			queryFn: async (): Promise<StepPreviewResponse> => {
				if (!isActiveStep) {
					throw new Error('Step is disabled');
				}
				const resourceConfig = analysisStore.resourceConfig as unknown as Record<
					string,
					unknown
				> | null;
				const result = await previewStepData({
					analysis_id: analysisId,
					datasource_id: datasourceId,
					pipeline_steps: activePipeline,
					target_step_id: stepId,
					row_limit: rowLimit,
					page: currentPage,
					resource_config: resourceConfig
				});
				if (result.isErr()) {
					throw new Error(result.error.message);
				}
				return result.value;
			},
			staleTime: Infinity
		};
	});

	const data = $derived(isActiveStep ? query.data : null);
	const isLoading = $derived(isActiveStep ? query.isLoading : false);
	const error = $derived(isActiveStep ? query.error : null);
	const totalPages = $derived(data ? Math.ceil(data.total_rows / rowLimit) : 0);
	const startRow = $derived((currentPage - 1) * rowLimit + 1);
	const endRow = $derived(data ? Math.min(currentPage * rowLimit, data.total_rows) : 0);

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
		const temporal = getTemporalType(data?.column_types?.[columnId]);
		if (temporal === 'date') return formatDateDisplay(value as string);
		if (temporal === 'datetime') return formatDateTimeDisplay(value as string);
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
		return resolveColumnType(data?.column_types?.[col]);
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

<div class="w-full my-2 overflow-hidden rounded-md border select-text bg-panel border-panel" style="box-shadow: var(--panel-shadow);">
	{#if isLoading}
		<div class="flex flex-col items-center justify-center gap-3 p-8 pointer-events-none text-fg-tertiary">
			<div class="spinner-md"></div>
			<p class="m-0 text-fg-tertiary">Loading preview...</p>
		</div>
	{:else if error}
		<div class="p-8 text-center">
			<p class="m-0 mb-2 font-semibold text-error-fg">Failed to load preview</p>
			<p class="m-0 text-fg-tertiary">{error.message}</p>
		</div>
	{:else if headerGroups.length > 0 && data}
		<div class="flex justify-between items-center px-4 py-3 text-xs border-b text-fg-tertiary border-panel" style="background: var(--panel-header-bg);">
			<span>
				Showing {startRow.toLocaleString()}-{endRow.toLocaleString()} of {data.total_rows.toLocaleString()}
				rows
			</span>
		</div>

		<div class="overflow-x-auto overflow-y-auto max-h-[400px]">
			<table class="w-full border-collapse">
				<thead class="sticky top-0 z-10" style="background: var(--table-header-bg);">
					{#each headerGroups as headerGroup (headerGroup.id)}
						<tr>
							{#each headerGroup.headers as header (header.id)}
								<th class="p-0 text-left font-semibold text-[0.8125rem] uppercase tracking-wide border-b-2 border-table">
									<button
										class="flex items-center gap-1 px-4 py-3 bg-transparent border-none cursor-pointer transition-colors hover:bg-hover"
										style="font-size: inherit; font-weight: inherit; color: inherit; text-transform: inherit; letter-spacing: inherit;"
										onclick={() => toggleSort(header.id)}
									>
										<span class="text-sm">
											{typeof header.column.columnDef.header === 'string'
												? header.column.columnDef.header
												: header.id}
										</span>
										{#if getSortDirection(header.id)}
											<span class="text-xs text-accent">
												{getSortDirection(header.id) === 'asc' ? '↑' : '↓'}
											</span>
										{/if}
									</button>
									{#if getColumnType(header.id)}
										<div class="inline-block ml-2 align-middle">
											<ColumnTypeBadge
												columnType={getColumnType(header.id)}
												size="xs"
												showIcon={false}
											/>
										</div>
									{/if}
								</th>
							{/each}
						</tr>
					{/each}
				</thead>
				<tbody>
					{#each rows as row (row.id)}
						<tr class="border-b transition-colors last:border-b-0 border-table even:bg-secondary hover:!bg-hover">
							{#each row.getVisibleCells() as cell (cell.id)}
								<td
									class="px-4 py-3 whitespace-nowrap overflow-hidden text-ellipsis max-w-[250px] text-[0.8125rem] select-text text-fg-secondary"
									class:text-xs={isListType(getColumnType(cell.column.id))}
								>
									{formatValue(cell.getValue() as TableCellValue, cell.column.id)}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if totalPages > 1}
			<div class="flex justify-between items-center px-4 py-3 border-t border-panel" style="background: var(--panel-header-bg);">
				<button
					class="px-4 py-2 border rounded-sm cursor-pointer transition-all border-primary bg-panel hover:bg-hover hover:border-secondary disabled:opacity-40 disabled:cursor-not-allowed"
					onclick={prevPage}
					disabled={currentPage === 1}
				>
					Previous
				</button>
				<span class="text-xs text-fg-tertiary">Page {currentPage} of {totalPages}</span>
				<button
					class="px-4 py-2 border rounded-sm cursor-pointer transition-all border-primary bg-panel hover:bg-hover hover:border-secondary disabled:opacity-40 disabled:cursor-not-allowed"
					onclick={nextPage}
					disabled={currentPage >= totalPages}
				>
					Next
				</button>
			</div>
		{/if}
	{:else}
		<div class="p-8 text-center text-fg-muted">
			<p class="m-0">No data available</p>
		</div>
	{/if}
</div>
