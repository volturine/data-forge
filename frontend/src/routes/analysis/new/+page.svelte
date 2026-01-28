<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { listDatasources } from '$lib/api/datasource';
	import { createAnalysis } from '$lib/api/analysis';
	import type { AnalysisCreate } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';

	let step = $state(1);
	let name = $state('');
	let description = $state('');
	let selectedDatasourceIds = $state<string[]>([]);
	let error = $state('');
	let creating = $state(false);
	let search = $state('');
	let showPicker = $state(false);

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
	const filteredDatasources = $derived.by(() => {
		const query = search.trim().toLowerCase();
		if (!query) return datasourceOptions;
		return datasourceOptions.filter((ds) => {
			const nameValue = ds.name.toLowerCase();
			const typeValue = ds.source_type.toLowerCase();
			const fileValue =
				ds.source_type === 'file' && ds.config?.file_type
					? String(ds.config.file_type).toLowerCase()
					: '';
			return nameValue.includes(query) || typeValue.includes(query) || fileValue.includes(query);
		});
	});

	function toggleDatasource(id: string) {
		if (selectedDatasourceIds.includes(id)) {
			selectedDatasourceIds = selectedDatasourceIds.filter((dsId) => dsId !== id);
		} else {
			selectedDatasourceIds = [...selectedDatasourceIds, id];
		}
	}

	function handlePickerFocus() {
		showPicker = true;
	}

	function handlePickerBlur() {
		setTimeout(() => {
			showPicker = false;
		}, 100);
	}

	function getSourceLabel(datasource: DataSource): string {
		if (datasource.source_type !== 'file') return datasource.source_type;
		if (!datasource.config?.file_type) return 'file';
		return String(datasource.config.file_type).toUpperCase();
	}

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

<div class="wizard-container">
	<div class="wizard-header">
		<h1>New Analysis</h1>
		<div class="steps-indicator">
			<div class="step" class:active={step === 1} class:completed={step > 1}>
				<span class="step-number">{step > 1 ? '✓' : '1'}</span>
				<span class="step-label">Details</span>
			</div>
			<div class="step-line" class:completed={step > 1}></div>
			<div class="step" class:active={step === 2} class:completed={step > 2}>
				<span class="step-number">{step > 2 ? '✓' : '2'}</span>
				<span class="step-label">Data Source</span>
			</div>
			<div class="step-line" class:completed={step > 2}></div>
			<div class="step" class:active={step === 3}>
				<span class="step-number">3</span>
				<span class="step-label">Review</span>
			</div>
		</div>
	</div>

	<div class="wizard-content">
		{#if step === 1}
			<div class="step-content">
				<h2>Analysis Details</h2>
				<p class="step-description">Give your analysis a name and optional description.</p>

				<div class="form-group">
					<label for="name">Name <span class="required">*</span></label>
					<input id="name" type="text" bind:value={name} placeholder="My Data Analysis" />
				</div>
				<div class="form-group">
					<label for="description">Description</label>
					<textarea
						id="description"
						bind:value={description}
						placeholder="Describe what this analysis does..."
						rows="4"
					></textarea>
				</div>
			</div>
		{:else if step === 2}
			<div class="step-content">
				<h2>Select Data Sources</h2>
				<p class="step-description">Choose one or more data sources for this analysis.</p>

				{#if datasourcesQuery.isLoading}
					<div class="info-box">Loading data sources...</div>
				{:else if datasourcesQuery.error}
					<div class="error-box">
						Error loading data sources: {datasourcesQuery.error.message}
					</div>
				{:else if datasourcesQuery.data && datasourcesQuery.data.length === 0}
					<div class="empty-state">
						<p>No data sources available.</p>
						<a href={resolve('/datasources/new')} class="btn btn-secondary" data-sveltekit-reload
							>Create Data Source</a
						>
					</div>
				{:else if datasourcesQuery.data}
					<div
						class="datasource-picker"
						role="combobox"
						aria-expanded={showPicker}
						aria-controls="analysis-datasource-options"
					>
						<span class="sr-only">Search datasources</span>
						<input
							type="text"
							class="search-input"
							placeholder="Search datasources..."
							bind:value={search}
							onfocus={handlePickerFocus}
							onblur={handlePickerBlur}
						/>
						{#if showPicker}
							<div class="picker-list" id="analysis-datasource-options" role="listbox">
								{#if filteredDatasources.length === 0}
									<div class="picker-empty">No matching datasources.</div>
								{:else}
									{#each filteredDatasources as datasource (datasource.id)}
										<button
											type="button"
											class="picker-item"
											data-selected={selectedDatasourceIds.includes(datasource.id)}
											onmousedown={() => toggleDatasource(datasource.id)}
										>
											<span class="picker-name">{datasource.name}</span>
											<span class="badge badge-neutral">{getSourceLabel(datasource)}</span>
										</button>
									{/each}
								{/if}
							</div>
						{/if}
					</div>
					<div class="selected-sources">
						{#if selectedDatasourceIds.length === 0}
							<p class="empty-message">No datasources selected.</p>
						{:else}
							{#each datasourceOptions.filter( (ds) => selectedDatasourceIds.includes(ds.id) ) as datasource (datasource.id)}
								<div class="source-chip">
									<span>{datasource.name}</span>
									<button
										type="button"
										onclick={() => toggleDatasource(datasource.id)}
										aria-label={`Remove ${datasource.name}`}
									>
										×
									</button>
								</div>
							{/each}
						{/if}
					</div>
				{/if}
			</div>
		{:else if step === 3}
			<div class="step-content">
				<h2>Review & Create</h2>
				<p class="step-description">Review your analysis configuration before creating.</p>

				<div class="review-section">
					<h3>Details</h3>
					<dl class="review-list">
						<div class="review-item">
							<dt>Name</dt>
							<dd>{name}</dd>
						</div>
						{#if description}
							<div class="review-item">
								<dt>Description</dt>
								<dd>{description}</dd>
							</div>
						{/if}
					</dl>
				</div>

				<div class="review-section">
					<h3>Data Sources ({selectedDatasourceIds.length})</h3>
					<ul class="review-sources">
						{#if datasourcesQuery.data}
							{#each datasourcesQuery.data.filter( (ds: DataSource) => selectedDatasourceIds.includes(ds.id) ) as ds (ds.id)}
								<li>
									<span class="source-name">{ds.name}</span>
									<span class="source-type">{ds.source_type}</span>
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

	<div class="wizard-footer">
		{#if step > 1}
			<button class="btn btn-secondary" onclick={() => (step -= 1)} disabled={creating}>
				Back
			</button>
		{:else}
			<a href={resolve('/')} class="btn btn-secondary" data-sveltekit-reload>Cancel</a>
		{/if}

		<div class="spacer"></div>

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

<style>
	.wizard-container {
		max-width: 720px;
		margin: 0 auto;
		padding: var(--space-7) var(--space-6);
		display: flex;
		flex-direction: column;
		min-height: calc(100vh - 60px);
		gap: var(--space-6);
	}

	.wizard-header {
		margin-bottom: var(--space-8);
	}
	.wizard-header h1 {
		margin: 0 0 var(--space-6) 0;
		font-size: var(--text-2xl);
		font-weight: var(--font-semibold);
	}

	.steps-indicator {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.step {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.step-number {
		width: 28px;
		height: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: var(--font-semibold);
		color: var(--fg-muted);
		background-color: var(--bg-primary);
	}
	.step.active .step-number {
		border-color: var(--accent-primary);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
	}
	.step.completed .step-number {
		border-color: var(--success-border);
		background-color: var(--success-bg);
		color: var(--success-fg);
	}

	.step-label {
		font-size: var(--text-sm);
		color: var(--fg-muted);
	}
	.step.active .step-label {
		color: var(--fg-primary);
		font-weight: var(--font-medium);
	}

	.step-line {
		flex: 1;
		height: 1px;
		background-color: var(--border-primary);
		min-width: 40px;
	}
	.step-line.completed {
		background-color: var(--success-border);
	}

	.wizard-content {
		flex: 1;
		margin-bottom: var(--space-6);
	}

	.step-content {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-6);
		box-shadow: var(--card-shadow);
	}
	.step-content h2 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-lg);
		font-weight: var(--font-semibold);
	}
	.step-description {
		color: var(--fg-tertiary);
		margin-bottom: var(--space-6);
	}

	.form-group {
		margin-bottom: var(--space-5);
	}
	.form-group label {
		display: block;
		margin-bottom: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		color: var(--fg-secondary);
	}
	.required {
		color: var(--error-fg);
	}

	.form-group input,
	.form-group textarea {
		width: 100%;
		padding: var(--space-3);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-primary);
	}
	.form-group input:focus,
	.form-group textarea:focus {
		outline: none;
		border-color: var(--border-focus);
	}
	.form-group textarea {
		resize: vertical;
		min-height: 100px;
	}

	.datasource-picker {
		position: relative;
		margin-bottom: var(--space-4);
	}
	.datasource-picker .search-input {
		width: 100%;
		padding: var(--space-3);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-primary);
	}
	.datasource-picker .search-input::placeholder {
		color: var(--fg-muted);
	}

	.picker-list {
		position: absolute;
		z-index: var(--z-dropdown);
		top: calc(100% + var(--space-2));
		left: 0;
		right: 0;
		background: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		box-shadow: var(--shadow-dropdown);
		max-height: 240px;
		overflow-y: auto;
		padding: var(--space-2);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.picker-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		border: 1px solid transparent;
		background: transparent;
		cursor: pointer;
		text-align: left;
	}
	.picker-item[data-selected='true'] {
		border-color: var(--accent-primary);
		background-color: var(--bg-hover);
	}
	.picker-item:hover {
		background-color: var(--bg-hover);
	}

	.picker-name {
		font-weight: var(--font-semibold);
	}
	.picker-empty {
		padding: var(--space-2);
		color: var(--fg-muted);
		font-style: italic;
	}

	.selected-sources {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-secondary);
	}

	.source-chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: 0.25rem 0.5rem;
		border-radius: var(--radius-full);
		background-color: var(--bg-tertiary);
		font-size: var(--text-xs);
		font-weight: var(--font-semibold);
	}
	.source-chip button {
		border: none;
		background: none;
		cursor: pointer;
		color: var(--fg-muted);
		line-height: 1;
		padding: 0;
	}
	.source-chip button:hover {
		color: var(--fg-primary);
	}

	.review-section {
		margin-bottom: var(--space-6);
		padding-bottom: var(--space-6);
		border-bottom: 1px solid var(--border-primary);
	}
	.review-section:last-of-type {
		border-bottom: none;
		margin-bottom: 0;
		padding-bottom: 0;
	}
	.review-section h3 {
		margin: 0 0 var(--space-4) 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		color: var(--fg-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.review-list {
		margin: 0;
	}
	.review-item {
		display: flex;
		gap: var(--space-4);
		margin-bottom: var(--space-2);
	}
	.review-item dt {
		width: 100px;
		flex-shrink: 0;
		color: var(--fg-muted);
	}
	.review-item dd {
		margin: 0;
	}

	.review-sources {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.review-sources li {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--border-primary);
	}
	.review-sources li:last-child {
		border-bottom: none;
	}
	.source-name {
		color: var(--fg-primary);
	}
	.source-type {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}

	.empty-state {
		text-align: center;
		padding: var(--space-8);
		color: var(--fg-tertiary);
		border: 1px dashed var(--border-primary);
		border-radius: var(--radius-sm);
	}

	.wizard-footer {
		display: flex;
		gap: var(--space-3);
		padding-top: var(--space-6);
		border-top: 1px solid var(--border-primary);
	}
	.spacer {
		flex: 1;
	}
</style>
