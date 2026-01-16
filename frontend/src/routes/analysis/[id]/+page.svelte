<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { computeStore } from '$lib/stores/compute.svelte';
	import { getAnalysis, updateAnalysis } from '$lib/api/analysis';
	import { getResultData } from '$lib/api/results';
	import { getDatasourceSchema } from '$lib/api/datasource';
	import type { PipelineStep } from '$lib/types/analysis';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DataTable from '$lib/components/viewers/DataTable.svelte';

	const analysisId = $derived($page.params.id);

	let selectedStepId = $state<string | null>(null);
	let showResults = $state(false);
	let isSaving = $state(false);
	let isRunning = $state(false);
	let saveStatus = $state<'saved' | 'unsaved' | 'saving'>('saved');
	let saveTimeout: ReturnType<typeof setTimeout> | null = null;
	let initialPipeline: PipelineStep[] | null = null;

	const analysisQuery = createQuery(() => ({
		queryKey: ['analysis', analysisId],
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			const analysis = await getAnalysis(analysisId);
			await analysisStore.loadAnalysis(analysisId);

			// Load schema for the first datasource
			if (analysis.pipeline_definition && 'datasource_ids' in analysis.pipeline_definition) {
				const datasourceIds = analysis.pipeline_definition.datasource_ids as string[];
				if (datasourceIds.length > 0) {
					try {
						const schema = await getDatasourceSchema(datasourceIds[0]);
						analysisStore.setSourceSchema(datasourceIds[0], schema);
					} catch (err) {
						console.error('Failed to load schema:', err);
					}
				}
			}

			return analysis;
		},
		retry: false
	}));

	let currentJob = $derived.by(() => {
		const jobs = Array.from(computeStore.jobs.values());
		const analysisJobs = jobs.filter((job) => {
			return job.result && typeof job.result === 'object' && 'analysis_id' in job.result;
		});
		return analysisJobs.length > 0 ? analysisJobs[analysisJobs.length - 1] : null;
	});

	const resultQuery = createQuery(() => ({
		queryKey: ['result', analysisId, currentJob?.id],
		queryFn: async () => {
			if (!analysisId || !currentJob || currentJob?.status !== 'completed') {
				return null;
			}
			return await getResultData(analysisId, 1, 100);
		},
		enabled: currentJob?.status === 'completed'
	}));

	function handleAddStep(type: string) {
		const step: PipelineStep = {
			id: crypto.randomUUID(),
			type,
			config: {},
			depends_on: []
		};
		analysisStore.addStep(step);
		selectedStepId = step.id;
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
	}

	function handleDeleteStep(stepId: string) {
		analysisStore.removeStep(stepId);
		if (selectedStepId === stepId) {
			selectedStepId = null;
		}
	}

	function handleUpdateStep(stepId: string, config: Record<string, unknown>) {
		analysisStore.updateStep(stepId, { config });
	}

	async function handleSave() {
		if (isSaving || saveStatus === 'saving') return;

		// Clear any pending autosave
		if (saveTimeout) {
			clearTimeout(saveTimeout);
			saveTimeout = null;
		}

		isSaving = true;
		saveStatus = 'saving';
		try {
			await analysisStore.save();
			saveStatus = 'saved';
		} catch (err) {
			saveStatus = 'unsaved';
			const message = err instanceof Error ? err.message : 'Failed to save pipeline';
			alert(message);
		} finally {
			isSaving = false;
		}
	}

	async function handleRun() {
		if (isRunning || !analysisId) return;

		isRunning = true;
		try {
			const job = await computeStore.executeAnalysis(analysisId);
			showResults = true;

			// Wait for job to complete (polling is handled by computeStore)
		} catch (err) {
			const message = err instanceof Error ? err.message : 'Failed to run analysis';
			alert(message);
		} finally {
			isRunning = false;
		}
	}

	function handleCloseConfig() {
		selectedStepId = null;
	}

	const selectedStep = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});

	// Autosave effect - watches pipeline changes
	$effect(() => {
		const pipeline = analysisStore.pipeline;

		// Skip autosave on initial load
		if (initialPipeline === null) {
			initialPipeline = pipeline;
			return;
		}

		// Skip if no real changes (same reference)
		if (pipeline === initialPipeline) {
			return;
		}

		// Clear previous timeout
		if (saveTimeout) {
			clearTimeout(saveTimeout);
			saveTimeout = null;
		}

		// Mark as unsaved
		saveStatus = 'unsaved';

		// Set new timeout for autosave
		saveTimeout = setTimeout(async () => {
			saveStatus = 'saving';
			try {
				await analysisStore.save();
				saveStatus = 'saved';
			} catch (err) {
				saveStatus = 'unsaved';
				console.error('Autosave failed:', err);
			}
		}, 3000);

		// Cleanup function
		return () => {
			if (saveTimeout) {
				clearTimeout(saveTimeout);
			}
		};
	});
</script>

{#if analysisQuery.isLoading}
	<div class="loading-container">
		<div class="spinner"></div>
		<p>Loading analysis...</p>
	</div>
{:else if analysisQuery.isError}
	<div class="error-container">
		<h2>Error Loading Analysis</h2>
		<p>{analysisQuery.error instanceof Error ? analysisQuery.error.message : 'Unknown error'}</p>
		<button onclick={() => goto('/analysis')} type="button">Back to Gallery</button>
	</div>
{:else if analysisQuery.data}
	<div class="editor-container">
		<!-- Header -->
		<header class="editor-header">
			<div class="header-left">
				<button class="back-button" onclick={() => goto('/')} type="button" title="Back to gallery">
					← Back
				</button>
				<h1>{analysisQuery.data.name}</h1>
				{#if analysisQuery.data.description}
					<span class="description">{analysisQuery.data.description}</span>
				{/if}
			</div>
			<div class="header-right">
				<span class="save-status" class:saved={saveStatus === 'saved'}>
					{#if saveStatus === 'saving'}
						Saving...
					{:else if saveStatus === 'unsaved'}
						Unsaved changes
					{:else}
						All changes saved
					{/if}
				</span>
				<button
					class="button-secondary"
					onclick={handleSave}
					disabled={isSaving || saveStatus === 'saving' || analysisStore.loading}
					type="button"
				>
					{isSaving || saveStatus === 'saving' ? 'Saving...' : 'Save'}
				</button>
				<button
					class="button-primary"
					onclick={handleRun}
					disabled={isRunning || analysisStore.pipeline.length === 0}
					type="button"
				>
					{isRunning ? 'Running...' : 'Run Analysis'}
				</button>
			</div>
		</header>

		<!-- Main workspace -->
		<div class="editor-workspace">
			<!-- Left sidebar: Step library -->
			<StepLibrary onAddStep={handleAddStep} />

			<!-- Center: Pipeline canvas -->
			<PipelineCanvas
				steps={analysisStore.pipeline}
				onStepClick={handleSelectStep}
				onStepDelete={handleDeleteStep}
			/>

			<!-- Right sidebar: Step config -->
			<StepConfig
				step={selectedStep}
				schema={analysisStore.calculatedSchema}
				onUpdateStep={handleUpdateStep}
				onClose={handleCloseConfig}
			/>
		</div>

		<!-- Bottom panel: Results viewer -->
		{#if showResults}
			<div class="results-panel" class:collapsed={!showResults}>
				<div class="results-header">
					<h3>Results</h3>
					<div class="results-actions">
						{#if currentJob}
							<span class="job-status" class:completed={currentJob?.status === 'completed'}>
								{currentJob?.status}
							</span>
						{/if}
						<button
							class="collapse-button"
							onclick={() => (showResults = !showResults)}
							type="button"
						>
							{showResults ? '▼' : '▲'}
						</button>
					</div>
				</div>

				<div class="results-content">
					{#if currentJob?.status === 'pending' || currentJob?.status === 'running'}
						<div class="loading-state">
							<div class="spinner"></div>
							<p>
								{currentJob?.status === 'pending' ? 'Analysis queued...' : 'Running analysis...'}
							</p>
							{#if currentJob?.progress !== undefined}
								<div class="progress-bar">
									<div class="progress-fill" style="width: {currentJob?.progress}%"></div>
								</div>
							{/if}
						</div>
					{:else if currentJob?.status === 'failed'}
						<div class="error-state">
							<p>Analysis failed</p>
							<span>{currentJob?.error || 'Unknown error'}</span>
						</div>
					{:else if currentJob?.status === 'completed' && resultQuery.data}
						<DataTable
							columns={resultQuery.data.columns}
							data={resultQuery.data.data}
							loading={resultQuery.isLoading}
						/>
					{:else if currentJob?.status === 'completed' && resultQuery.isLoading}
						<div class="loading-state">
							<div class="spinner"></div>
							<p>Loading results...</p>
						</div>
					{:else}
						<div class="empty-state">
							<p>Run the analysis to see results</p>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}

<style>
	.loading-container,
	.error-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100vh;
		gap: 1rem;
	}

	.spinner {
		width: 40px;
		height: 40px;
		border: 4px solid #f3f4f6;
		border-top-color: #3b82f6;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.loading-container p,
	.error-container p {
		color: #6b7280;
		margin: 0;
	}

	.error-container h2 {
		color: #ef4444;
		margin: 0;
	}

	.error-container button {
		margin-top: 1rem;
		padding: 0.5rem 1rem;
		background: #3b82f6;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.editor-container {
		display: flex;
		flex-direction: column;
		height: 100vh;
		background: #fff;
	}

	.editor-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem 1.5rem;
		border-bottom: 1px solid #e5e7eb;
		background: white;
		gap: 1rem;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 1rem;
		min-width: 0;
		flex: 1;
	}

	.back-button {
		padding: 0.5rem 0.75rem;
		background: none;
		border: 1px solid #d1d5db;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
		color: #374151;
		transition: all 0.2s;
		flex-shrink: 0;
	}

	.back-button:hover {
		background: #f9fafb;
		border-color: #9ca3af;
	}

	.editor-header h1 {
		margin: 0;
		font-size: 1.25rem;
		color: #111827;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.description {
		font-size: 0.875rem;
		color: #6b7280;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.header-right {
		display: flex;
		gap: 0.75rem;
		flex-shrink: 0;
		align-items: center;
	}

	.save-status {
		font-size: 0.875rem;
		color: #9ca3af;
		white-space: nowrap;
	}

	.save-status.saved {
		color: #6b7280;
	}

	.button-primary,
	.button-secondary {
		padding: 0.5rem 1rem;
		border: none;
		border-radius: 4px;
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s;
		white-space: nowrap;
	}

	.button-primary {
		background: #3b82f6;
		color: white;
	}

	.button-primary:hover:not(:disabled) {
		background: #2563eb;
	}

	.button-primary:disabled {
		background: #9ca3af;
		cursor: not-allowed;
	}

	.button-secondary {
		background: white;
		color: #374151;
		border: 1px solid #d1d5db;
	}

	.button-secondary:hover:not(:disabled) {
		background: #f9fafb;
	}

	.button-secondary:disabled {
		color: #9ca3af;
		cursor: not-allowed;
	}

	.editor-workspace {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	.results-panel {
		border-top: 1px solid #e5e7eb;
		background: white;
		max-height: 400px;
		display: flex;
		flex-direction: column;
	}

	.results-panel.collapsed {
		max-height: 48px;
	}

	.results-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid #e5e7eb;
		background: #f9fafb;
	}

	.results-header h3 {
		margin: 0;
		font-size: 0.875rem;
		font-weight: 600;
		color: #111827;
	}

	.results-actions {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.job-status {
		font-size: 0.75rem;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
		background: #fef3c7;
		color: #92400e;
		text-transform: uppercase;
		font-weight: 600;
	}

	.job-status.completed {
		background: #d1fae5;
		color: #065f46;
	}

	.collapse-button {
		padding: 0.25rem 0.5rem;
		background: none;
		border: 1px solid #d1d5db;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
		color: #6b7280;
	}

	.collapse-button:hover {
		background: #f3f4f6;
	}

	.results-content {
		flex: 1;
		overflow-y: auto;
	}

	.loading-state,
	.error-state,
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 3rem;
		gap: 1rem;
	}

	.loading-state p,
	.error-state p,
	.empty-state p {
		margin: 0;
		color: #6b7280;
		font-size: 0.875rem;
	}

	.error-state p {
		color: #ef4444;
		font-weight: 600;
	}

	.error-state span {
		font-size: 0.875rem;
		color: #6b7280;
	}

	.progress-bar {
		width: 200px;
		height: 4px;
		background: #e5e7eb;
		border-radius: 2px;
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		background: #3b82f6;
		transition: width 0.3s ease;
	}
</style>
