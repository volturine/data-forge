<script lang="ts">
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { listDatasources } from '$lib/api/datasource';
	import { createAnalysis } from '$lib/api/analysis';
	import type { DataSource } from '$lib/types/datasource';

	let step = $state(1);
	let name = $state('');
	let description = $state('');
	let selectedDatasourceIds = $state<string[]>([]);
	let error = $state('');
	let creating = $state(false);

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: listDatasources
	}));

	const canProceedStep1 = $derived(name.trim().length > 0);
	const canProceedStep2 = $derived(selectedDatasourceIds.length > 0);

	function toggleDatasource(id: string) {
		if (selectedDatasourceIds.includes(id)) {
			selectedDatasourceIds = selectedDatasourceIds.filter((dsId) => dsId !== id);
		} else {
			selectedDatasourceIds = [...selectedDatasourceIds, id];
		}
	}

	async function handleCreate() {
		if (!canProceedStep1 || !canProceedStep2) return;

		creating = true;
		error = '';

		try {
			const analysis = await createAnalysis({
				name: name.trim(),
				description: description.trim() || null,
				datasource_ids: selectedDatasourceIds,
				pipeline_steps: []
			});

			goto(`/analysis/${analysis.id}`);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to create analysis';
			creating = false;
		}
	}
</script>

<div class="wizard-container">
	<div class="wizard-header">
		<h1>Create New Analysis</h1>
		<div class="steps-indicator">
			<div class="step" class:active={step === 1} class:completed={step > 1}>
				<div class="step-number">1</div>
				<div class="step-label">Details</div>
			</div>
			<div class="step-line" class:completed={step > 1}></div>
			<div class="step" class:active={step === 2} class:completed={step > 2}>
				<div class="step-number">2</div>
				<div class="step-label">Data Source</div>
			</div>
			<div class="step-line" class:completed={step > 2}></div>
			<div class="step" class:active={step === 3}>
				<div class="step-number">3</div>
				<div class="step-label">Review</div>
			</div>
		</div>
	</div>

	<div class="wizard-content">
		{#if step === 1}
			<div class="step-content">
				<h2>Analysis Details</h2>
				<div class="form-group">
					<label for="name">Name <span class="required">*</span></label>
					<input id="name" type="text" bind:value={name} placeholder="My Data Analysis" autofocus />
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
				<p class="hint">Choose one or more data sources for this analysis</p>

				{#if datasourcesQuery.isLoading}
					<div class="loading">Loading data sources...</div>
				{:else if datasourcesQuery.error}
					<div class="error-message">
						Error loading data sources: {datasourcesQuery.error.message}
					</div>
				{:else if datasourcesQuery.data && datasourcesQuery.data.length === 0}
					<div class="empty-state">
						<p>No data sources available.</p>
						<a href="/datasources/new" class="btn btn-secondary">Create Data Source</a>
					</div>
				{:else if datasourcesQuery.data}
					<div class="datasource-grid">
						{#each datasourcesQuery.data as datasource}
							<button
								class="datasource-card"
								class:selected={selectedDatasourceIds.includes(datasource.id)}
								onclick={() => toggleDatasource(datasource.id)}
							>
								<div class="card-header">
									<h3>{datasource.name}</h3>
									<span class="type-badge">{datasource.source_type}</span>
								</div>
								<div class="card-info">
									<span class="created-date">
										Created {new Date(datasource.created_at).toLocaleDateString()}
									</span>
								</div>
								{#if selectedDatasourceIds.includes(datasource.id)}
									<div class="selected-indicator">✓</div>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>
		{:else if step === 3}
			<div class="step-content">
				<h2>Review & Create</h2>
				<div class="review-section">
					<h3>Analysis Details</h3>
					<dl>
						<dt>Name:</dt>
						<dd>{name}</dd>
						{#if description}
							<dt>Description:</dt>
							<dd>{description}</dd>
						{/if}
					</dl>
				</div>
				<div class="review-section">
					<h3>Data Sources ({selectedDatasourceIds.length})</h3>
					<ul>
						{#if datasourcesQuery.data}
							{#each datasourcesQuery.data.filter( (ds: DataSource) => selectedDatasourceIds.includes(ds.id) ) as ds}
								<li>{ds.name} ({ds.source_type})</li>
							{/each}
						{/if}
					</ul>
				</div>
				{#if error}
					<div class="error-message">{error}</div>
				{/if}
			</div>
		{/if}
	</div>

	<div class="wizard-footer">
		<div class="footer-actions">
			{#if step > 1}
				<button class="btn btn-secondary" onclick={() => (step -= 1)} disabled={creating}>
					Back
				</button>
			{:else}
				<a href="/" class="btn btn-secondary">Cancel</a>
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
</div>

<style>
	.wizard-container {
		max-width: 800px;
		margin: 0 auto;
		padding: 2rem;
		display: flex;
		flex-direction: column;
		min-height: calc(100vh - 4rem);
	}

	.wizard-header h1 {
		margin: 0 0 2rem 0;
		font-size: 2rem;
		font-weight: 600;
	}

	.steps-indicator {
		display: flex;
		align-items: center;
		gap: 1rem;
		margin-bottom: 3rem;
	}

	.step {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}

	.step-number {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		border: 2px solid #ddd;
		display: flex;
		align-items: center;
		justify-content: center;
		font-weight: 600;
		background: white;
		color: #999;
	}

	.step.active .step-number {
		border-color: #4f46e5;
		background: #4f46e5;
		color: white;
	}

	.step.completed .step-number {
		border-color: #10b981;
		background: #10b981;
		color: white;
	}

	.step-label {
		font-size: 0.875rem;
		color: #666;
	}

	.step.active .step-label {
		color: #4f46e5;
		font-weight: 600;
	}

	.step-line {
		flex: 1;
		height: 2px;
		background: #ddd;
		min-width: 60px;
	}

	.step-line.completed {
		background: #10b981;
	}

	.wizard-content {
		flex: 1;
		margin-bottom: 2rem;
	}

	.step-content {
		background: white;
		border: 1px solid #e5e7eb;
		border-radius: 8px;
		padding: 2rem;
	}

	.step-content h2 {
		margin: 0 0 1.5rem 0;
		font-size: 1.5rem;
		font-weight: 600;
	}

	.hint {
		color: #666;
		margin-bottom: 1.5rem;
	}

	.form-group {
		margin-bottom: 1.5rem;
	}

	.form-group label {
		display: block;
		margin-bottom: 0.5rem;
		font-weight: 500;
		color: #374151;
	}

	.required {
		color: #ef4444;
	}

	.form-group input,
	.form-group textarea {
		width: 100%;
		padding: 0.75rem;
		border: 1px solid #d1d5db;
		border-radius: 6px;
		font-size: 1rem;
		font-family: inherit;
	}

	.form-group input:focus,
	.form-group textarea:focus {
		outline: none;
		border-color: #4f46e5;
		box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
	}

	.datasource-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
		gap: 1rem;
	}

	.datasource-card {
		position: relative;
		padding: 1.5rem;
		border: 2px solid #e5e7eb;
		border-radius: 8px;
		background: white;
		cursor: pointer;
		transition: all 0.2s;
		text-align: left;
	}

	.datasource-card:hover {
		border-color: #4f46e5;
		box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
	}

	.datasource-card.selected {
		border-color: #4f46e5;
		background: #f5f3ff;
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: start;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	.card-header h3 {
		margin: 0;
		font-size: 1rem;
		font-weight: 600;
		color: #111827;
	}

	.type-badge {
		padding: 0.25rem 0.5rem;
		background: #e5e7eb;
		border-radius: 4px;
		font-size: 0.75rem;
		color: #6b7280;
		white-space: nowrap;
	}

	.card-info {
		font-size: 0.875rem;
		color: #6b7280;
	}

	.selected-indicator {
		position: absolute;
		top: 1rem;
		right: 1rem;
		width: 24px;
		height: 24px;
		background: #4f46e5;
		color: white;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.875rem;
	}

	.review-section {
		margin-bottom: 2rem;
	}

	.review-section h3 {
		margin: 0 0 1rem 0;
		font-size: 1.125rem;
		font-weight: 600;
		color: #111827;
	}

	.review-section dl {
		display: grid;
		grid-template-columns: 120px 1fr;
		gap: 0.75rem;
		margin: 0;
	}

	.review-section dt {
		font-weight: 500;
		color: #6b7280;
	}

	.review-section dd {
		margin: 0;
		color: #111827;
	}

	.review-section ul {
		margin: 0;
		padding-left: 1.5rem;
		color: #111827;
	}

	.review-section li {
		margin-bottom: 0.5rem;
	}

	.loading,
	.empty-state {
		text-align: center;
		padding: 3rem;
		color: #6b7280;
	}

	.error-message {
		padding: 1rem;
		background: #fee2e2;
		border: 1px solid #ef4444;
		border-radius: 6px;
		color: #991b1b;
		margin-top: 1rem;
	}

	.wizard-footer {
		border-top: 1px solid #e5e7eb;
		padding-top: 1.5rem;
	}

	.footer-actions {
		display: flex;
		gap: 1rem;
	}

	.spacer {
		flex: 1;
	}

	.btn {
		padding: 0.75rem 1.5rem;
		border: none;
		border-radius: 6px;
		font-size: 1rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
		text-decoration: none;
		display: inline-block;
	}

	.btn-primary {
		background: #4f46e5;
		color: white;
	}

	.btn-primary:hover:not(:disabled) {
		background: #4338ca;
	}

	.btn-primary:disabled {
		background: #9ca3af;
		cursor: not-allowed;
	}

	.btn-secondary {
		background: white;
		color: #374151;
		border: 1px solid #d1d5db;
	}

	.btn-secondary:hover:not(:disabled) {
		background: #f9fafb;
	}

	.btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
