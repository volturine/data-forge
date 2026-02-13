<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { listDatasources, deleteDatasource } from '$lib/api/datasource';
	import { Plus, Trash2, Search, LoaderCircle } from 'lucide-svelte';
	import DatasourcePreview from '$lib/components/datasources/DatasourcePreview.svelte';
	import DatasourceConfigPanel from '$lib/components/datasources/DatasourceConfigPanel.svelte';
	import SnapshotPicker from '$lib/components/datasources/SnapshotPicker.svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';

	const queryClient = useQueryClient();

	const query = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const deleteMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteDatasource(id);
			if (result.isErr()) throw new Error(result.error.message);
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['datasources'] });
			if (selectedId === deletingId) {
				selectDatasource(null);
			}
		}
	}));

	let selectedId = $state<string | null>(page.url.searchParams.get('id'));
	let showConfig = $state<string | null>(page.url.searchParams.get('id'));
	let deletingId = $state<string | null>(null);
	let searchQuery = $state('');

	const datasources = $derived(query.data ?? []);
	const filteredDatasources = $derived(
		searchQuery
			? datasources.filter((d) => d.name.toLowerCase().includes(searchQuery.toLowerCase()))
			: datasources
	);
	const selectedDatasource = $derived(datasources.find((d) => d.id === selectedId) ?? null);
	let snapshotConfig = $state<Record<string, unknown> | null>(null);

	function selectDatasource(id: string | null) {
		selectedId = id;
		showConfig = id;
		snapshotConfig = null;
		const url = id ? `/datasources?id=${id}` : '/datasources';
		goto(resolve(url as '/'), { replaceState: true });
	}

	function handleDelete(id: string) {
		deletingId = id;
		deleteMutation.mutate(id);
	}

	function handleConfigSaved() {
		queryClient.invalidateQueries({ queryKey: ['datasources'] });
	}

	function handleSnapshotConfigChange(config: Record<string, unknown>) {
		snapshotConfig = config;
	}
</script>

<div class="flex h-full">
	<!-- Left Pane -->
	<aside
		class="w-(--datasource-panel-width) border-r border-tertiary flex flex-col bg-bg-primary shrink-0"
	>
		<!-- Header -->
		<header class="flex flex-col gap-2 px-4 py-3 border-b border-tertiary h-25 box-border">
			<div class="flex items-center justify-between">
				<h1 class="text-sm font-semibold">Data Sources</h1>
				<a
					href={resolve('/datasources/new')}
						class="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 no-underline bg-accent text-bg-primary border border-accent-primary"
					data-sveltekit-reload
				>
					<Plus size={14} />
					Add
				</a>
			</div>
			<div class="relative">
				<Search size={14} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" />
				<input
					type="text"
					placeholder="Search datasources..."
					class="w-full bg-transparent border border-tertiary px-3 py-1 pl-8 text-sm"
					bind:value={searchQuery}
				/>
			</div>
		</header>

		<!-- Datasource List -->
		<div class="flex-1 overflow-y-auto">
			{#if query.isLoading}
				<div class="flex h-full items-center justify-center">
					<div class="spinner"></div>
				</div>
			{:else if query.isError}
				<div class="error-box m-4 text-sm">
					Error: {query.error instanceof Error ? query.error.message : 'Unknown error'}
				</div>
			{:else if datasources.length === 0}
				<div class="p-8 text-center">
					<p class="text-sm text-fg-muted mb-4">No data sources yet.</p>
					<a
						href={resolve('/datasources/new')}
					class="inline-flex items-center gap-1 text-sm font-medium px-3 py-2 no-underline bg-accent text-bg-primary border border-accent-primary"
						data-sveltekit-reload
					>
						Create your first data source
					</a>
				</div>
			{:else if filteredDatasources.length === 0}
				<div class="p-8 text-center text-sm text-fg-muted">
					No datasources match "{searchQuery}"
				</div>
			{:else}
				{#each filteredDatasources as datasource (datasource.id)}
					<div
						class="datasource-item border-b border-tertiary"
						class:selected={selectedId === datasource.id}
					>
						<!-- Row -->
						<div class="flex items-center justify-between px-3 py-2.5">
							<button
								class="flex items-center min-w-0 flex-1 text-left bg-transparent p-0 border-transparent"
								onclick={() => selectDatasource(datasource.id)}
							>
								<span
									class="font-medium truncate text-sm"
									class:text-accent-primary={selectedId === datasource.id}
								>
									{datasource.name}
								</span>
							</button>
							<div class="flex items-center shrink-0">
								<button
									class="action-icon p-1.5 bg-transparent border-transparent hover:text-error-fg"
									title="Delete"
									onclick={() => handleDelete(datasource.id)}
									disabled={deleteMutation.isPending && deletingId === datasource.id}
								>
									{#if deleteMutation.isPending && deletingId === datasource.id}
										<LoaderCircle size={14} class="spinning" />
									{:else}
										<Trash2 size={14} />
									{/if}
								</button>
							</div>
						</div>

						<!-- Inline Config Panel -->
						{#if showConfig === datasource.id}
							<DatasourceConfigPanel {datasource} onSave={handleConfigSaved} />
						{/if}
					</div>
				{/each}
			{/if}
		</div>
	</aside>

	<!-- Right Pane -->
	<main class="flex-1 overflow-hidden">
		{#if selectedDatasource}
			<div class="h-full flex flex-col">
				<div class="border-b border-tertiary bg-bg-secondary p-3">
					{#if selectedDatasource.source_type === 'iceberg'}
						<SnapshotPicker
							datasourceId={selectedDatasource.id}
							datasourceConfig={snapshotConfig ?? selectedDatasource.config}
							label="Time Travel"
							showDelete
							onConfigChange={handleSnapshotConfigChange}
						/>
					{:else}
						<div class="text-xs text-fg-tertiary">
							Time travel is available for Iceberg datasources.
						</div>
					{/if}
				</div>
				<div class="flex-1 min-h-0 overflow-hidden">
					<DatasourcePreview
						datasourceId={selectedDatasource.id}
						datasourceConfig={snapshotConfig ?? selectedDatasource.config}
					/>
				</div>
			</div>
		{:else}
			<div class="h-full flex items-center justify-center text-fg-muted bg-secondary">
				<div class="text-center">
					<p class="text-lg font-medium mb-2">No datasource selected</p>
					<p class="text-sm">Select a datasource from the list to preview</p>
				</div>
			</div>
		{/if}
	</main>
</div>
