<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { getAnalysis } from '$lib/api/analysis';
	import { getDatasourceSchema } from '$lib/api/datasource';
	import type { PipelineStep } from '$lib/types/analysis';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';

	const analysisId = $derived($page.params.id);

	let selectedStepId = $state<string | null>(null);
	let isSaving = $state(false);
	let saveStatus = $state<'saved' | 'unsaved' | 'saving'>('saved');
	let saveTimeout: ReturnType<typeof setTimeout> | null = null;
	let initialPipeline: PipelineStep[] | null = null;

	let isLoadingSchema = $state(false);

	const analysisQuery = createQuery(() => ({
		queryKey: ['analysis', analysisId],
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			const analysis = await getAnalysis(analysisId);
			await analysisStore.loadAnalysis(analysisId);

			return analysis;
		},
		retry: false
	}));

	$effect(() => {
		const datasourceIdValue = datasourceId;
		if (!datasourceIdValue) return;

		const existingSchema = analysisStore.sourceSchemas.get(datasourceIdValue);
		if (existingSchema) return;

		isLoadingSchema = true;
		getDatasourceSchema(datasourceIdValue)
			.then((schema) => {
				analysisStore.setSourceSchema(datasourceIdValue, schema);
			})
			.catch((err) => {
				console.error('Failed to load schema:', err);
			})
			.finally(() => {
				isLoadingSchema = false;
			});
	});

	const datasourceId = $derived.by(() => {
		const analysis = analysisQuery.data;
		if (!analysis?.pipeline_definition) return undefined;
		const datasourceIds = (analysis.pipeline_definition as { datasource_ids?: string[] }).datasource_ids;
		return datasourceIds?.[0];
	});

	function makeId() {
		if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
			return crypto.randomUUID();
		}
		return 'id-' + Math.random().toString(16).slice(2) + Date.now().toString(16);
	}

	function handleAddStep(type: string) {
		const step: PipelineStep = {
			id: makeId(),
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

	async function handleSave() {
		if (isSaving || saveStatus === 'saving') return;

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

	function handleCloseConfig() {
		selectedStepId = null;
	}

	const selectedStep = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});

	$effect(() => {
		const pipeline = analysisStore.pipeline;

		if (initialPipeline === null) {
			initialPipeline = pipeline;
			return;
		}

		if (pipeline === initialPipeline) {
			return;
		}

		if (saveTimeout) {
			clearTimeout(saveTimeout);
			saveTimeout = null;
		}

		saveStatus = 'unsaved';

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
		<div class="error-icon">!</div>
		<h2>Error loading analysis</h2>
		<p>{analysisQuery.error instanceof Error ? analysisQuery.error.message : 'Unknown error'}</p>
		<button onclick={() => goto('/', { invalidateAll: true })} type="button">Back to Gallery</button
		>
	</div>
{:else if analysisQuery.data}
	<div class="editor-container">
		<header class="editor-header">
			<div class="header-left">
				<button
					class="back-button"
					onclick={() => goto('/', { invalidateAll: true })}
					type="button"
					aria-label="Go back to home"
				>
					<svg
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
					>
						<path d="M19 12H5M12 19l-7-7 7-7" />
					</svg>
				</button>
				<div class="header-title">
					<h1>{analysisQuery.data.name}</h1>
					{#if analysisQuery.data.description}
						<span class="description">{analysisQuery.data.description}</span>
					{/if}
				</div>
			</div>
			<div class="header-right">
				<span
					class="save-status"
					class:saved={saveStatus === 'saved'}
					class:unsaved={saveStatus === 'unsaved'}
				>
					{#if saveStatus === 'saving'}
						saving...
					{:else if saveStatus === 'unsaved'}
						unsaved
					{:else}
						saved
					{/if}
				</span>
				<button
					class="btn btn-secondary"
					onclick={handleSave}
					disabled={isSaving || saveStatus === 'saving' || analysisStore.loading}
					type="button"
				>
					Save
				</button>
			</div>
		</header>

		<div class="editor-workspace">
			<StepLibrary onAddStep={handleAddStep} />

			<PipelineCanvas
				steps={analysisStore.pipeline}
				{datasourceId}
				onStepClick={handleSelectStep}
				onStepDelete={handleDeleteStep}
			/>

			<StepConfig
				step={selectedStep}
				schema={analysisStore.calculatedSchema}
				{isLoadingSchema}
				onClose={handleCloseConfig}
			/>
		</div>
	</div>
{/if}

<style>
	.loading-container,
	.error-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: calc(100vh - 60px);
		gap: var(--space-4);
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 2px solid var(--border-primary);
		border-top-color: var(--fg-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.loading-container p {
		color: var(--fg-tertiary);
		font-size: var(--text-sm);
	}

	.error-container {
		text-align: center;
	}

	.error-icon {
		width: 52px;
		height: 52px;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--error-bg);
		color: var(--error-fg);
		border: 1px solid var(--error-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-xl);
		font-weight: 700;
		box-shadow: var(--shadow-soft);
	}

	.error-container h2 {
		margin: 0;
		font-size: var(--text-lg);
		color: var(--fg-primary);
	}

	.error-container p {
		margin: 0;
		color: var(--fg-tertiary);
		font-size: var(--text-sm);
	}

	.error-container button {
		margin-top: var(--space-4);
		padding: var(--space-2) var(--space-4);
		background-color: var(--accent-primary);
		color: var(--bg-primary);
		border: 1px solid var(--accent-primary);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		cursor: pointer;
		box-shadow: var(--card-shadow);
	}

	.editor-container {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 60px);
		background-color: var(--bg-secondary);
		gap: var(--space-4);
	}

	.editor-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-4) var(--space-5);
		border-bottom: 1px solid var(--border-primary);
		background-color: var(--bg-primary);
		gap: var(--space-4);
		box-shadow: var(--shadow-soft);
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-width: 0;
		flex: 1;
	}

	.back-button {
		padding: var(--space-2);
		background: transparent;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		cursor: pointer;
		color: var(--fg-secondary);
		transition: all var(--transition-fast);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.back-button:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.header-title {
		min-width: 0;
	}

	.editor-header h1 {
		margin: 0;
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--fg-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.description {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}

	.header-right {
		display: flex;
		gap: var(--space-3);
		flex-shrink: 0;
		align-items: center;
	}

	.save-status {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		background-color: var(--bg-tertiary);
	}

	.save-status.saved {
		color: var(--success-fg);
		background-color: var(--success-bg);
	}

	.save-status.unsaved {
		color: var(--warning-fg);
		background-color: var(--warning-bg);
	}

	.btn {
		padding: var(--space-2) var(--space-4);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.btn-secondary {
		background-color: transparent;
		color: var(--fg-primary);
		border-color: var(--border-secondary);
	}

	.btn-secondary:hover:not(:disabled) {
		background-color: var(--bg-hover);
	}

	.btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.editor-workspace {
		display: flex;
		flex: 1;
		overflow: hidden;
	}
</style>
