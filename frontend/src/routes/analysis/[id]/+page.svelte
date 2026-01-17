<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { getAnalysis } from '$lib/api/analysis';
	import { getDatasourceSchema } from '$lib/api/datasource';
	import type { PipelineStep } from '$lib/types/analysis';

	type AnalysisTab = {
		id: string;
		name: string;
		type: 'datasource' | 'derived';
		parent_id: string | null;
		datasource_id: string | null;
	};
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';

	const analysisId = $derived($page.params.id);

	let selectedStepId = $state<string | null>(null);
	let isSaving = $state(false);
	let saveStatus = $state<'saved' | 'unsaved' | 'saving'>('saved');
	let saveTimeout: ReturnType<typeof setTimeout> | null = null;
	let initialPipeline: PipelineStep[] | null = null;
	let initialTabs: AnalysisTab[] | null = null;
	let tabName = $state('');

	let isLoadingSchema = $state(false);
	let selectedLibraryType = $state<string | null>(null);
	let activeTarget = $state<{ index: number; parentId: string | null; nextId: string | null; valid: boolean } | null>(null);
	const store = analysisStore as unknown as {
		insertStep: (step: PipelineStep, index: number, parentId: string | null, nextId: string | null) => boolean;
		addBranchStep: (step: PipelineStep, parentId: string | null) => void;
		setActiveTab: (id: string) => void;
		addTab: (tab: AnalysisTab) => void;
		updateTab: (id: string, updates: Partial<AnalysisTab>) => void;
		removeTab: (id: string) => void;
		activeTab: AnalysisTab | null;
		tabs: AnalysisTab[];
	};

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

	function buildStep(type: string): PipelineStep {
		return {
			id: makeId(),
			type,
			config: {},
			depends_on: []
		};
	}

	function handleAddStep(type: string) {
		const step = buildStep(type);
		analysisStore.addStep(step);
		selectedStepId = step.id;
	}

	function handleInsertStep(type: string, targetIndex: number, parentId: string | null, nextId: string | null) {
		const step = buildStep(type);
		const inserted = store.insertStep(step, targetIndex, parentId, nextId);
		if (!inserted) {
			return;
		}
		selectedLibraryType = null;
		selectedStepId = step.id;
		activeTarget = null;
	}

	function handleBranchStep(type: string, parentId: string | null) {
		const step = buildStep(type);
		store.addBranchStep(step, parentId);
		selectedLibraryType = null;
		selectedStepId = step.id;
		activeTarget = null;
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
	}

	function handleSelectTab(tabId: string) {
		store.setActiveTab(tabId);
	}

	function getTabLabel(tab: AnalysisTab): string {
		if (tab.type !== 'derived' || !tab.parent_id) {
			return tab.name;
		}
		const parent = store.tabs.find((item: AnalysisTab) => item.id === tab.parent_id);
		if (!parent) {
			return tab.name;
		}
		return `${parent.name} → ${tab.name}`;
	}

	function handleAddDerived() {
		const current = store.activeTab;
		if (!current) {
			return;
		}
		const count = store.tabs.filter((tab: AnalysisTab) => tab.type === 'derived').length + 1;
		const tab: AnalysisTab = {
			id: makeId(),
			name: `Derived ${count}`,
			type: 'derived',
			parent_id: current.id,
			datasource_id: null
		};
		store.addTab(tab);
		tabName = tab.name;
	}

	function handleTabName(value: string) {
		const current = store.activeTab;
		if (!current) {
			return;
		}
		store.updateTab(current.id, { name: value });
		tabName = value;
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

	function handleDragStart(type: string) {
		selectedLibraryType = type;
	}

	function handleDragEnd() {
		selectedLibraryType = null;
	}

	function handleSelectLibraryType(type: string | null) {
		selectedLibraryType = type;
	}

	const selectedStep = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});

	$effect(() => {
		const current = store.activeTab;
		if (!current) {
			tabName = '';
			return;
		}
		tabName = current.name;
	});

	$effect(() => {
		const pipeline = analysisStore.pipeline;
		const tabs = store.tabs;

		if (initialPipeline === null && initialTabs === null) {
			initialPipeline = pipeline;
			initialTabs = tabs;
			return;
		}

		if (pipeline === initialPipeline && tabs === initialTabs) {
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

		<div class="analysis-tabs">
			<div class="tabs">
				{#each store.tabs as tab (tab.id)}
					<button
						class="tab"
						class:active={store.activeTab?.id === tab.id}
						onclick={() => handleSelectTab(tab.id)}
						type="button"
					>
						{getTabLabel(tab)}
					</button>
				{/each}
				{#if store.activeTab?.type === 'derived' && store.activeTab?.id}
					<button
					class="tab"
					onclick={() => store.activeTab?.id && store.removeTab(store.activeTab.id)}
					type="button"
				>
					Remove
				</button>
				{/if}
				<button class="tab" onclick={handleAddDerived} type="button">
					+ Derived
				</button>
			</div>
			{#if store.activeTab}
				<div class="tab-settings">
					<label for="tab-name">Tab name</label>
					<input
						id="tab-name"
						type="text"
						value={tabName}
						oninput={(event) => handleTabName(event.currentTarget.value)}
					/>
				</div>
			{/if}
		</div>

		<div class="editor-workspace">
			<StepLibrary
				onAddStep={handleAddStep}
				onInsertStep={(type, target) =>
					handleInsertStep(type, target.index, target.parentId, target.nextId)
				}
				onBranchStep={(type, parentId) => handleBranchStep(type, parentId)}
				onDragStart={handleDragStart}
				onDragEnd={handleDragEnd}
				selectedType={selectedLibraryType}
				onSelectType={handleSelectLibraryType}
			/>
			<PipelineCanvas
				steps={analysisStore.pipeline}
				datasourceId={datasourceId}
				onStepClick={handleSelectStep}
				onStepDelete={handleDeleteStep}
				onInsertStep={(type, target) =>
					handleInsertStep(type, target.index, target.parentId, target.nextId)
				}
				onBranchStep={(type, parentId) => handleBranchStep(type, parentId)}
				selectedType={selectedLibraryType}
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

	.analysis-tabs {
		padding: 0 var(--space-5);
	}

	.tabs {
		display: flex;
		gap: var(--space-3);
		border-bottom: 1px solid var(--border-primary);
		padding-bottom: var(--space-2);
		margin-bottom: var(--space-3);
		flex-wrap: wrap;
	}

	.tab {
		padding: var(--space-2) var(--space-3);
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--fg-muted);
		font-family: var(--font-mono);
		transition: all var(--transition-fast);
	}

	.tab:hover {
		color: var(--fg-secondary);
	}

	.tab.active {
		color: var(--accent-primary);
		border-bottom-color: var(--accent-primary);
	}

	.tab-settings {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}

	.tab-settings label {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.tab-settings input {
		flex: 1;
		max-width: 320px;
		padding: var(--space-2);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-primary);
		color: var(--fg-primary);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}

	.editor-workspace {
		display: flex;
		flex: 1;
		overflow: hidden;
	}
</style>
