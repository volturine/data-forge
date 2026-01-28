<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { listDatasources, deleteDatasource } from '$lib/api/datasource';
	import { Plus, ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';
	import DatasourcePreview from '$lib/components/datasources/DatasourcePreview.svelte';

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
	let expandedPreview = $state<string | null>(null);

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

	function togglePreview(id: string) {
		expandedPreview = expandedPreview === id ? null : id;
	}

	function isExpanded(id: string): boolean {
		return expandedPreview === id;
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
		<a href={resolve('/datasources/new')} class="btn-primary btn-new" data-sveltekit-reload>
			<Plus size={16} />
			Add Data Source
		</a>
	</header>

	{#if query.isLoading}
		<div class="info-box loading-state">Loading data sources...</div>
	{:else if query.isError}
		<div class="error-box">
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
			<div class="list-container">
				<div class="list-header">
					<span class="col-expand"></span>
					<span class="col-name">Name</span>
					<span class="col-type">Type</span>
					<span class="col-rows">Rows</span>
					<span class="col-columns">Columns</span>
					<span class="col-created">Created</span>
					<span class="col-actions">Actions</span>
				</div>
				{#each query.data as datasource (datasource.id)}
					<div class="list-item" class:expanded={isExpanded(datasource.id)}>
						<div class="list-row">
							<span class="col-expand">
								<button
									class="expand-btn"
									onclick={() => togglePreview(datasource.id)}
									aria-expanded={isExpanded(datasource.id)}
									aria-label={isExpanded(datasource.id) ? 'Collapse preview' : 'Expand preview'}
								>
									{#if isExpanded(datasource.id)}
										<ChevronUp size={16} />
									{:else}
										<ChevronDown size={16} />
									{/if}
								</button>
							</span>
							<span class="col-name">{datasource.name}</span>
							<span class="col-type">
								<span
									class="badge"
									class:badge-info={datasource.source_type === 'file'}
									class:badge-success={datasource.source_type === 'database'}
									class:badge-warning={datasource.source_type === 'api'}
								>
									{#if datasource.source_type === 'file'}
										{getFileType(datasource) ?? 'file'}
									{:else}
										{datasource.source_type}
									{/if}
								</span>
							</span>
							<span class="col-rows">{formatRowCount(getRowCount(datasource))}</span>
							<span class="col-columns">{getColumnCount(datasource)}</span>
							<span class="col-created">{formatDate(datasource.created_at)}</span>
							<span class="col-actions">
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
							</span>
						</div>
						{#if isExpanded(datasource.id)}
							<div class="preview-panel">
								<DatasourcePreview datasourceId={datasource.id} datasourceName={datasource.name} />
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<style>
	.container {
		max-width: 1000px;
		margin: 0 auto;
		padding: var(--space-6);
		height: 100%;
		overflow: auto;
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
		font-weight: var(--font-semibold);
	}
	.subtitle {
		margin: 0;
		color: var(--fg-tertiary);
	}
	.btn-new {
		text-decoration: none;
		box-shadow: var(--card-shadow);
	}

	.loading-state {
		text-align: center;
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

	.list-container {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		overflow: hidden;
	}

	.list-header,
	.list-row {
		display: grid;
		grid-template-columns: 48px 1fr 100px 90px 90px 110px 140px;
		align-items: center;
		gap: var(--space-4);
	}
	.list-header {
		padding: var(--space-4) var(--space-5);
		font-size: var(--text-xs);
		font-weight: var(--font-semibold);
		color: var(--fg-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background-color: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-primary);
	}

	.list-item {
		border-bottom: 1px solid var(--border-primary);
	}
	.list-item:last-child {
		border-bottom: none;
	}

	.list-row {
		padding: var(--space-4) var(--space-5);
		color: var(--fg-secondary);
	}
	.list-row:hover {
		background-color: var(--bg-hover);
	}

	.col-name {
		font-weight: var(--font-medium);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.col-rows,
	.col-columns {
		font-variant-numeric: tabular-nums;
	}
	.col-created {
		color: var(--fg-muted);
	}
	.col-actions {
		white-space: nowrap;
	}

	.expand-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		padding: 0;
		background: transparent;
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		color: var(--fg-tertiary);
		cursor: pointer;
		transition: all var(--transition);
	}
	.expand-btn:hover {
		background: var(--bg-hover);
		color: var(--fg-primary);
		border-color: var(--border-secondary);
	}

	.preview-panel {
		padding: var(--space-4);
		background: var(--bg-secondary);
		border-top: 1px solid var(--border-primary);
	}
	.confirm-actions {
		display: flex;
		gap: var(--space-2);
	}
</style>
