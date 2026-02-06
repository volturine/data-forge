<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { listDatasources, deleteDatasource } from '$lib/api/datasource';
	import { Plus, ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';
	import DatasourcePreview from '$lib/components/datasources/DatasourcePreview.svelte';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import { formatDateDisplay } from '$lib/utils/datetime';
	import { goto } from '$app/navigation';

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
		return formatDateDisplay(dateString);
	}
</script>

<div class="mx-auto min-h-full max-w-[1000px] p-6">
	<header
		class="mb-8 flex items-start justify-between gap-6 border-b border-border-primary pb-6"
	>
		<div>
			<h1 class="m-0 mb-2 text-2xl font-semibold">Data Sources</h1>
			<p class="m-0 text-fg-tertiary">Manage your data connections and files</p>
		</div>
		<a
			href={resolve('/datasources/new')}
			class="btn-primary no-underline shadow-[var(--card-shadow)]"
			data-sveltekit-reload
		>
			<Plus size={16} />
			Add Data Source
		</a>
	</header>

	{#if query.isLoading}
		<div class="info-box text-center">Loading data sources...</div>
	{:else if query.isError}
		<div class="error-box">
			Error loading data sources: {query.error instanceof Error
				? query.error.message
				: 'Unknown error'}
		</div>
	{:else if query.data}
		{#if query.data.length === 0}
			<div
				class="rounded-sm border border-dashed border-border-secondary bg-bg-primary p-12 text-center"
			>
				<div
					class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-sm border border-border-primary text-xl text-fg-muted"
				>
					+
				</div>
				<p class="m-0 mb-6 text-fg-tertiary">No data sources yet.</p>
				<a href={resolve('/datasources/new')} class="btn btn-primary" data-sveltekit-reload
					>Create your first data source</a
				>
			</div>
		{:else}
			<div
				class="overflow-hidden rounded-sm border border-border-primary bg-bg-primary"
			>
				<div
					class="grid grid-cols-[48px_1fr_100px_90px_90px_110px_140px] items-center gap-4 border-b border-border-primary bg-bg-tertiary px-5 py-4 text-xs font-semibold uppercase tracking-wide text-fg-tertiary"
				>
					<span></span>
					<span>Name</span>
					<span>Type</span>
					<span>Rows</span>
					<span>Columns</span>
					<span>Created</span>
					<span>Actions</span>
				</div>
				{#each query.data as datasource (datasource.id)}
					<div
						class="list-item border-b border-border-primary"
						class:expanded={isExpanded(datasource.id)}
					>
						<div
							class="list-row grid grid-cols-[48px_1fr_100px_90px_90px_110px_140px] items-center gap-4 px-5 py-4 text-fg-secondary hover:bg-bg-hover"
						>
							<span>
								<button
									class="expand-btn flex h-7 w-7 items-center justify-center rounded-sm border border-transparent bg-transparent text-fg-tertiary transition-all hover:border-border-secondary hover:bg-bg-hover hover:text-fg-primary"
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
							<span class="overflow-hidden text-ellipsis whitespace-nowrap font-medium"
								>{datasource.name}</span
							>
							<span>
								{#if datasource.source_type === 'file'}
									<FileTypeBadge path={(datasource.config?.file_path as string) ?? ''} size="sm" />
								{:else}
									<FileTypeBadge
										sourceType={datasource.source_type as 'database' | 'api' | 'iceberg' | 'duckdb'}
										size="sm"
									/>
								{/if}
							</span>
							<span class="tabular-nums">{formatRowCount(getRowCount(datasource))}</span>
							<span class="tabular-nums">{getColumnCount(datasource)}</span>
							<span class="text-fg-muted">{formatDate(datasource.created_at)}</span>
							<span class="flex items-center whitespace-nowrap">
								{#if confirmingDelete === datasource.id}
									<div class="flex items-center gap-2">
										<span class="text-xs font-medium text-error-fg">Delete?</span>
										<button
											onclick={() => confirmDelete(datasource.id)}
											class="btn btn-danger btn-sm"
											disabled={deleteMutation.isPending}
										>
											Yes
										</button>
										<button onclick={cancelDelete} class="btn btn-secondary btn-sm"> No </button>
									</div>
								{:else}
									<div class="flex items-center gap-2">
										<button
											onclick={() => goto(resolve(`/datasources/${datasource.id}`))}
											class="btn btn-ghost btn-sm"
										>
											Edit
										</button>
										<button
											onclick={() => handleDelete(datasource.id)}
											class="btn btn-ghost btn-sm btn-delete hover:text-error-fg"
											disabled={deleteMutation.isPending}
										>
											Delete
										</button>
									</div>
								{/if}
							</span>
						</div>
						{#if isExpanded(datasource.id)}
							<div
								class="border-t border-border-primary bg-bg-secondary p-4"
							>
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
	.list-item:last-child {
		border-bottom: none;
	}
</style>
