<script lang="ts">
	import { goto } from '$app/navigation';
	import { Check } from 'lucide-svelte';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { listDatasources } from '$lib/api/datasource';
	import { createAnalysis } from '$lib/api/analysis';
	import DatasourcePicker from '$lib/components/common/DatasourcePicker.svelte';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { AnalysisCreate } from '$lib/types/analysis';

	let step = $state(1);
	let name = $state('');
	let description = $state('');
	let selectedDatasourceIds = $state<string[]>([]);
	let error = $state('');
	let creating = $state(false);

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: async () => {
			const result = await listDatasources();
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		}
	}));

	const canProceedStep1 = $derived(name.trim().length > 0);
	const canProceedStep2 = $derived(selectedDatasourceIds.length > 0);
	const datasourceOptions = $derived.by(() => datasourcesQuery.data ?? []);

	async function handleCreate() {
		if (!canProceedStep1 || !canProceedStep2) return;

		creating = true;
		error = '';

		const payload = {
			name: name.trim(),
			description: description.trim() || null,
			datasource_ids: selectedDatasourceIds,
			pipeline_steps: [],
			tabs: selectedDatasourceIds.map((datasourceId, index) => ({
				id: `tab-${datasourceId}`,
				name: `Source ${index + 1}`,
				type: 'datasource' as const,
				parent_id: null,
				datasource_id: datasourceId,
				steps: []
			}))
		};

		const result = await createAnalysis(payload as AnalysisCreate);
		result.match(
			(analysis) => {
				goto(resolve(`/analysis/${analysis.id}`), { invalidateAll: true });
			},
			(err) => {
				error = err.message;
				creating = false;
			}
		);
	}
</script>

<div class="mx-auto flex max-w-180 flex-col gap-6 px-6 py-7">
	<div class="mb-8">
		<h1 class="m-0 mb-6 text-2xl font-semibold">New Analysis</h1>
		<div class="flex items-center gap-2">
			<div
				class="step flex items-center gap-2 border-tertiary text-fg-muted bg-bg-primary"
				class:active={step === 1}
				class:completed={step > 1}
			>
				<span
					class="step-number flex h-7 w-7 items-center justify-center border border-tertiary text-xs font-semibold text-fg-muted bg-bg-primary"
				>
					{#if step > 1}
						<Check size={12} />
					{:else}
						1
					{/if}
				</span>
				<span class="text-sm text-fg-muted">Details</span>
			</div>
			<div
				class="step-line min-w-10 flex-1 h-px bg-border-primary"
				class:completed={step > 1}
			></div>
			<div
				class="step flex items-center gap-2 border-tertiary text-fg-muted bg-bg-primary"
				class:active={step === 2}
				class:completed={step > 2}
			>
				<span
					class="step-number flex h-7 w-7 items-center justify-center border border-tertiary text-xs font-semibold text-fg-muted bg-bg-primary"
				>
					{#if step > 2}
						<Check size={12} />
					{:else}
						2
					{/if}
				</span>
				<span class="text-sm text-fg-muted">Data Source</span>
			</div>
			<div
				class="step-line min-w-10 flex-1 h-px bg-border-primary"
				class:completed={step > 2}
			></div>
			<div
				class="step flex items-center gap-2 border-tertiary text-fg-muted bg-bg-primary"
				class:active={step === 3}
			>
				<span
					class="step-number flex h-7 w-7 items-center justify-center border border-tertiary text-xs font-semibold text-fg-muted bg-bg-primary"
				>
					3
				</span>
				<span class="text-sm text-fg-muted">Review</span>
			</div>
		</div>
	</div>

	<div class="mb-6 flex-1">
		{#if step === 1}
			<div class="card">
				<h2 class="m-0 mb-2 text-lg font-semibold">Analysis Details</h2>
				<p class="mb-6 text-fg-tertiary">Give your analysis a name and optional description.</p>

				<div class="mb-5 flex flex-col gap-2">
					<label for="name" class="block text-sm font-medium text-fg-secondary">
						Name <span class="text-error-fg">*</span>
					</label>
					<input
						id="name"
						type="text"
						bind:value={name}
						placeholder="My Data Analysis"
						class="w-full border border-tertiary bg-bg-primary p-3 text-sm focus:border-info"
					/>
				</div>
				<div class="mb-5 flex flex-col gap-2">
					<label for="description" class="block text-sm font-medium text-fg-secondary"
						>Description</label
					>
					<textarea
						id="description"
						bind:value={description}
						placeholder="Describe what this analysis does..."
						rows="4"
						class="min-h-25 w-full resize-y border border-tertiary bg-bg-primary p-3 text-sm focus:border-info"
					></textarea>
				</div>
			</div>
		{:else if step === 2}
			<div class="card">
				<h2 class="m-0 mb-2 text-lg font-semibold">Select Data Sources</h2>
				<p class="mb-6 text-fg-tertiary">Choose one or more data sources for this analysis.</p>

				{#if datasourcesQuery.isLoading}
					<div class="info-box">Loading data sources...</div>
				{:else if datasourcesQuery.error}
					<div class="error-box">
						Error loading data sources: {datasourcesQuery.error.message}
					</div>
				{:else if datasourcesQuery.data && datasourcesQuery.data.length === 0}
					<div
						class="rounded-sm border border-dashed border-tertiary p-8 text-center text-fg-tertiary"
					>
						<p>No data sources available.</p>
						<a href={resolve('/datasources/new')} class="btn btn-secondary" data-sveltekit-reload
							>Create Data Source</a
						>
					</div>
				{:else if datasourcesQuery.data}
					<DatasourcePicker
						datasources={datasourceOptions}
						bind:selected={selectedDatasourceIds}
						mode="multi"
						id="new-analysis"
						showChips={true}
						searchFields={['name', 'source_type', 'file_type']}
					/>
				{/if}
			</div>
		{:else if step === 3}
			<div class="card">
				<h2 class="m-0 mb-2 text-lg font-semibold">Review & Create</h2>
				<p class="mb-6 text-fg-tertiary">Review your analysis configuration before creating.</p>

				<div class="mb-6 border-b border-tertiary pb-6">
					<h3 class="m-0 mb-4 text-sm font-semibold uppercase tracking-wide text-fg-tertiary">
						Details
					</h3>
					<dl class="m-0">
						<div class="mb-2 flex gap-4">
							<dt class="w-25 shrink-0 text-fg-muted">Name</dt>
							<dd class="m-0">{name}</dd>
						</div>
						{#if description}
							<div class="mb-2 flex gap-4">
								<dt class="w-25 shrink-0 text-fg-muted">Description</dt>
								<dd class="m-0">{description}</dd>
							</div>
						{/if}
					</dl>
				</div>

				<div>
					<h3 class="m-0 mb-4 text-sm font-semibold uppercase tracking-wide text-fg-tertiary">
						Data Sources ({selectedDatasourceIds.length})
					</h3>
					<ul class="m-0 list-none p-0">
						{#if datasourcesQuery.data}
							{#each datasourcesQuery.data.filter( (ds) => selectedDatasourceIds.includes(ds.id) ) as ds (ds.id)}
								<li class="flex items-center gap-3 border-b border-tertiary py-2">
									<span class="text-fg-primary">{ds.name}</span>
									<span class="text-xs text-fg-muted">
										{#if ds.source_type === 'file'}
											<FileTypeBadge
												path={(ds.config?.file_path as string) ?? ''}
												size="sm"
												showIcon={true}
											/>
										{:else}
											<FileTypeBadge
												sourceType={ds.source_type as 'database' | 'api' | 'iceberg' | 'duckdb'}
												size="sm"
												showIcon={true}
											/>
										{/if}
									</span>
								</li>
							{/each}
						{/if}
					</ul>
				</div>

				{#if error}
					<div class="error-box">{error}</div>
				{/if}
			</div>
		{/if}
	</div>

	<div class="flex gap-3 border-t border-tertiary pt-6">
		{#if step > 1}
			<button class="btn btn-secondary" onclick={() => (step -= 1)} disabled={creating}>
				Back
			</button>
		{:else}
			<a href={resolve('/')} class="btn btn-secondary" data-sveltekit-reload>Cancel</a>
		{/if}

		<div class="flex-1"></div>

		{#if step < 3}
			<button
				class="btn btn-primary"
				onclick={() => (step += 1)}
				disabled={(step === 1 && !canProceedStep1) || (step === 2 && !canProceedStep2)}
			>
				Next
			</button>
		{:else}
			<button class="btn btn-primary" onclick={handleCreate} disabled={creating}>
				{creating ? 'Creating...' : 'Create Analysis'}
			</button>
		{/if}
	</div>
</div>
