<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { listDatasources, deleteDatasource } from '$lib/api/datasource';
	import { Plus } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';

	const queryClient = useQueryClient();

	const query = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		}
	}));

	const deleteMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteDatasource(id);
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
		}
	}));

	let confirmingDelete = $state<string | null>(null);

	function handleDelete(id: string) {
		confirmingDelete = id;
	}

	function confirmDelete(id: string) {
		deleteMutation.mutate(id);
		confirmingDelete = null;
	}

	function cancelDelete() {
		confirmingDelete = null;
	}

	function getColumnCount(datasource: DataSource): number {
		if (datasource.schema_cache && typeof datasource.schema_cache === 'object') {
			const schema = datasource.schema_cache as { columns?: unknown[] };
			if (Array.isArray(schema.columns)) {
				return schema.columns.length;
			}
		}
		return 0;
	}

	function getRowCount(datasource: DataSource): number | null {
		if (datasource.schema_cache && typeof datasource.schema_cache === 'object') {
			const schema = datasource.schema_cache as { row_count?: number | null };
			return schema.row_count ?? null;
		}
		return null;
	}

	function formatRowCount(count: number | null): string {
		if (count === null) return '-';
		if (count >= 1_000_000) {
			return `${(count / 1_000_000).toFixed(1)}M`;
		}
		if (count >= 1_000) {
			return `${(count / 1_000).toFixed(1)}K`;
		}
		return count.toLocaleString();
	}

	function formatDate(dateString: string): string {
		const date = new Date(dateString);
		return date.toLocaleDateString();
	}

	function getFileType(datasource: DataSource): string | null {
		if (datasource.source_type !== 'file') return null;
		if (!datasource.config || typeof datasource.config !== 'object') return null;
		const config = datasource.config as { file_type?: string };
		return config.file_type ?? null;
	}
</script>

<div class="container">
	<header class="page-header">
		<div class="header-text">
			<h1>Data Sources</h1>
			<p class="subtitle">Manage your data connections and files</p>
		</div>
		<a href={resolve('/datasources/new')} class="btn-new" data-sveltekit-reload>
			<Plus size={16} />
			Add Data Source
		</a>
	</header>

	{#if query.isLoading}
		<div class="loading-state">Loading data sources...</div>
	{:else if query.isError}
		<div class="error-state">
			Error loading data sources: {query.error instanceof Error
				? query.error.message
				: 'Unknown error'}
		</div>
	{:else if query.data}
		{#if query.data.length === 0}
			<div class="empty-state">
				<div class="empty-icon">+</div>
				<p>No data sources yet.</p>
				<a href={resolve('/datasources/new')} class="btn btn-primary" data-sveltekit-reload
					>Create your first data source</a
				>
			</div>
		{:else}
			<div class="table-container">
				<table>
					<thead>
						<tr>
							<th>Name</th>
							<th>Type</th>
							<th>Rows</th>
							<th>Columns</th>
							<th>Created</th>
							<th class="actions-col">Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each query.data as datasource (datasource.id)}
							<tr>
								<td class="name-cell">{datasource.name}</td>
								<td>
									<span
										class="type-badge"
										class:file={datasource.source_type === 'file'}
										class:database={datasource.source_type === 'database'}
										class:api={datasource.source_type === 'api'}
									>
										{#if datasource.source_type === 'file'}
											{getFileType(datasource) ?? 'file'}
										{:else}
											{datasource.source_type}
										{/if}
									</span>
								</td>
								<td class="num-cell">{formatRowCount(getRowCount(datasource))}</td>
								<td class="num-cell">{getColumnCount(datasource)}</td>
								<td class="date-cell">{formatDate(datasource.created_at)}</td>
								<td class="actions-cell">
									{#if confirmingDelete === datasource.id}
										<div class="confirm-actions">
											<button
												onclick={() => confirmDelete(datasource.id)}
												class="btn btn-danger btn-sm"
												disabled={deleteMutation.isPending}
											>
												Confirm
											</button>
											<button onclick={cancelDelete} class="btn btn-secondary btn-sm">
												Cancel
											</button>
										</div>
									{:else}
										<button
											onclick={() => handleDelete(datasource.id)}
											class="btn btn-ghost btn-sm"
											disabled={deleteMutation.isPending}
										>
											Delete
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>

<style>
	.container {
		max-width: 1000px;
		margin: 0 auto;
		padding: var(--space-6);
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-6);
		margin-bottom: var(--space-8);
		padding-bottom: var(--space-6);
		border-bottom: 1px solid var(--border-primary);
	}

	.header-text h1 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-2xl);
		font-weight: 600;
	}

	.subtitle {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--fg-tertiary);
	}

	.btn-new {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: 1px solid var(--accent-primary);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		text-decoration: none;
		cursor: pointer;
		transition: opacity var(--transition);
		box-shadow: var(--card-shadow);
	}

	.btn-new:hover {
		opacity: 0.9;
	}

	.loading-state {
		padding: var(--space-8);
		text-align: center;
		color: var(--fg-tertiary);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
	}

	.error-state {
		padding: var(--space-6);
		text-align: center;
		background-color: var(--error-bg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		color: var(--error-fg);
	}

	.empty-state {
		text-align: center;
		padding: var(--space-12);
		background-color: var(--bg-primary);
		border: 1px dashed var(--border-secondary);
		border-radius: var(--radius-sm);
	}

	.empty-icon {
		width: 48px;
		height: 48px;
		margin: 0 auto var(--space-4);
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		font-size: var(--text-xl);
		color: var(--fg-muted);
	}

	.empty-state p {
		margin: 0 0 var(--space-6) 0;
		color: var(--fg-tertiary);
	}

	.table-container {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	th {
		text-align: left;
		padding: var(--space-3) var(--space-4);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--fg-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background-color: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-primary);
	}

	td {
		padding: var(--space-4);
		font-size: var(--text-sm);
		border-bottom: 1px solid var(--border-primary);
		color: var(--fg-secondary);
	}

	tr:last-child td {
		border-bottom: none;
	}

	tr:hover td {
		background-color: var(--bg-hover);
	}

	.name-cell {
		font-weight: 500;
		color: var(--fg-primary);
	}

	.num-cell {
		font-variant-numeric: tabular-nums;
	}

	.date-cell {
		color: var(--fg-muted);
	}

	.actions-col {
		width: 150px;
	}

	.actions-cell {
		white-space: nowrap;
	}

	.type-badge {
		display: inline-block;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: 500;
		border: 1px solid;
	}

	.type-badge.file {
		color: var(--info-fg);
		background-color: var(--info-bg);
		border-color: var(--info-border);
	}

	.type-badge.database {
		color: var(--success-fg);
		background-color: var(--success-bg);
		border-color: var(--success-border);
	}

	.type-badge.api {
		color: var(--warning-fg);
		background-color: var(--warning-bg);
		border-color: var(--warning-border);
	}

	.confirm-actions {
		display: flex;
		gap: var(--space-2);
	}

	.btn {
		padding: var(--space-2) var(--space-3);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
		text-decoration: none;
	}

	.btn-sm {
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-xs);
	}

	.btn-primary {
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border-color: var(--accent-primary);
	}

	.btn-primary:hover {
		opacity: 0.85;
	}

	.btn-secondary {
		background-color: transparent;
		color: var(--fg-primary);
		border-color: var(--border-secondary);
	}

	.btn-secondary:hover {
		background-color: var(--bg-hover);
	}

	.btn-ghost {
		background-color: transparent;
		color: var(--fg-tertiary);
		border-color: transparent;
	}

	.btn-ghost:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.btn-danger {
		background-color: var(--error-bg);
		color: var(--error-fg);
		border-color: var(--error-border);
	}

	.btn-danger:hover {
		opacity: 0.85;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
