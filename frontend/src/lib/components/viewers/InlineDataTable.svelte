<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query'
	import { previewStepData, type StepPreviewRequest, type StepPreviewResponse } from '$lib/api/compute'
	import type { TableCellValue } from '$lib/types/api-responses'

	interface Props {
		datasourceId: string
		pipeline: Array<{
			id: string
			type: string
			config: Record<string, unknown>
		}>
		stepId: string
		rowLimit?: number
	}

	let { datasourceId, pipeline, stepId, rowLimit = 1000 }: Props = $props()
	let currentPage = $state(1)

	// Query key includes pipeline to trigger re-fetch on changes
	const query = createQuery(() => ({
		queryKey: ['step-preview', datasourceId, stepId, pipeline, currentPage],
		queryFn: async (): Promise<StepPreviewResponse> => {
			return await previewStepData({
				datasource_id: datasourceId,
				pipeline_steps: pipeline,
				target_step_id: stepId,
				row_limit: rowLimit,
				page: currentPage
			})
		},
		staleTime: 30000, // 30 seconds
		enabled: !!datasourceId && !!stepId && pipeline.length > 0
	}))

	const data = $derived(query.data)
	const isLoading = $derived(query.isLoading)
	const error = $derived(query.error)

	const totalPages = $derived(data ? Math.ceil(data.total_rows / rowLimit) : 0)
	const startRow = $derived((currentPage - 1) * rowLimit + 1)
	const endRow = $derived(data ? Math.min(currentPage * rowLimit, data.total_rows) : 0)

	function nextPage() {
		if (currentPage < totalPages) {
			currentPage++
		}
	}

	function prevPage() {
		if (currentPage > 1) {
			currentPage--
		}
	}

	function formatValue(value: TableCellValue): string {
		if (value === null || value === undefined) return '—'
		if (typeof value === 'number') {
			return value.toLocaleString()
		}
		if (typeof value === 'boolean') {
			return value ? 'true' : 'false'
		}
		return String(value)
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
	{:else if data}
		<div class="table-info">
			Showing {startRow.toLocaleString()}-{endRow.toLocaleString()} of {data.total_rows.toLocaleString()} rows
		</div>

		<div class="table-wrapper">
			<table>
				<thead>
					<tr>
						{#each data.columns as col (col)}
							<th>
								<span class="column-name">{col}</span>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each data.data as row, idx (idx)}
						<tr>
							{#each data.columns as col (col)}
								<td>{formatValue(row[col] as TableCellValue)}</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if totalPages > 1}
			<div class="pagination">
				<button onclick={prevPage} disabled={currentPage === 1}>
					Previous
				</button>
				<span class="page-info">
					Page {currentPage} of {totalPages}
				</span>
				<button onclick={nextPage} disabled={currentPage >= totalPages}>
					Next
				</button>
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
		background: #fff;
		border: 1px solid #e5e7eb;
		border-radius: 6px;
		overflow: hidden;
		margin: 8px 0;
		font-size: 0.875rem;
	}

	.loading-overlay {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 2rem;
		gap: 0.75rem;
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 3px solid #f3f4f6;
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

	.error-state {
		padding: 2rem;
		text-align: center;
	}

	.error-title {
		margin: 0 0 0.5rem 0;
		color: #dc2626;
		font-weight: 600;
	}

	.error-message {
		margin: 0;
		color: #6b7280;
		font-size: 0.875rem;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
	}

	.empty-state p {
		margin: 0;
		color: #9ca3af;
		font-size: 0.875rem;
	}

	.table-info {
		padding: 0.75rem 1rem;
		font-size: 0.75rem;
		color: #6b7280;
		background: #f9fafb;
		border-bottom: 1px solid #e5e7eb;
	}

	.table-wrapper {
		overflow-x: auto;
		max-height: 400px;
		overflow-y: auto;
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	thead {
		position: sticky;
		top: 0;
		background: #f9fafb;
		z-index: 10;
	}

	th {
		padding: 0.75rem 1rem;
		text-align: left;
		border-bottom: 2px solid #e5e7eb;
		font-weight: 600;
		color: #374151;
	}

	.column-name {
		font-family: 'Courier New', monospace;
		font-size: 0.875rem;
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
		max-width: 250px;
	}

	.pagination {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem 1rem;
		background: #f9fafb;
		border-top: 1px solid #e5e7eb;
	}

	.pagination button {
		padding: 0.5rem 1rem;
		border: 1px solid #d1d5db;
		border-radius: 4px;
		background: #fff;
		color: #374151;
		font-size: 0.875rem;
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.pagination button:hover:not(:disabled) {
		background: #f9fafb;
		border-color: #9ca3af;
	}

	.pagination button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.page-info {
		font-size: 0.75rem;
		color: #6b7280;
	}
</style>
