<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { FiniteStateMachine } from 'runed';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { getAnalysis } from '$lib/api/analysis';
	import { getDatasourceSchema, listDatasources } from '$lib/api/datasource';
	import { sendKeepalive, spawnEngine } from '$lib/api/compute';
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import { getDefaultConfig } from '$lib/utils/step-config-defaults';
	import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
	import type { DropTarget } from '$lib/stores/drag.svelte';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DragPreview from '$lib/components/pipeline/DragPreview.svelte';
	import DatasourceSelectorModal from '$lib/components/common/DatasourceSelectorModal.svelte';
	import { SvelteMap } from 'svelte/reactivity';

	const analysisId = $derived($page.params.id);

	let selectedStepId = $state<string | null>(null);
	let selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let previewVersions = $state(new SvelteMap<string, number>());
	let lastPreviewPipelines = $state(new SvelteMap<string, string>());
	let draftLoaded = $state(false);

	// Track pipeline state at last preview to detect staleness
	const activeTabId = $derived(analysisStore.activeTab?.id ?? null);
	const currentPipelineKey = $derived(JSON.stringify(analysisStore.pipeline));
	const previewVersion = $derived(activeTabId ? (previewVersions.get(activeTabId) ?? 0) : 0);
	const lastPreviewPipeline = $derived(
		activeTabId ? (lastPreviewPipelines.get(activeTabId) ?? '') : ''
	);
	const isPreviewStale = $derived(!!previewVersion && lastPreviewPipeline !== currentPipelineKey);
	const storageKey = $derived(analysisId ? `analysis-draft:${analysisId}` : null);

	function handlePreview() {
		if (!activeTabId) return;
		const next = (previewVersions.get(activeTabId) ?? 0) + 1;
		previewVersions.set(activeTabId, next);
		lastPreviewPipelines.set(activeTabId, currentPipelineKey);
		if (analysisId) {
			// wait 1 second
			setTimeout(() => {
				sendKeepalive(analysisId);
			}, 1000);
		}
	}

	$effect(() => {
		if (!analysisId) return;
		draftLoaded = false;
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!storageKey || draftLoaded) return;
		if (!analysisStore.tabs.length) return;
		const raw = window.localStorage.getItem(storageKey);
		if (!raw) {
			draftLoaded = true;
			return;
		}
		const parsed = JSON.parse(raw) as {
			analysisId: string;
			tabs: AnalysisTab[];
			activeTabId: string | null;
			resourceConfig: EngineResourceConfig | null;
			engineDefaults: EngineDefaults | null;
			previewVersions: Record<string, number>;
			lastPreviewPipelines: Record<string, string>;
			selectedStepId: string | null;
			leftPaneCollapsed: boolean;
			rightPaneCollapsed: boolean;
			saveStatus: SaveStates;
		};
		if (parsed.analysisId !== analysisId) {
			draftLoaded = true;
			return;
		}
		analysisStore.setTabs(parsed.tabs);
		analysisStore.activeTabId = parsed.activeTabId;
		analysisStore.setResourceConfig(parsed.resourceConfig);
		analysisStore.setEngineDefaults(parsed.engineDefaults);
		selectedStepId = parsed.selectedStepId;
		leftPaneCollapsed = parsed.leftPaneCollapsed;
		rightPaneCollapsed = parsed.rightPaneCollapsed;
		const versions = new SvelteMap<string, number>();
		for (const [key, value] of Object.entries(parsed.previewVersions ?? {})) {
			versions.set(key, value);
		}
		previewVersions = versions;
		const pipelines = new SvelteMap<string, string>();
		for (const [key, value] of Object.entries(parsed.lastPreviewPipelines ?? {})) {
			pipelines.set(key, value);
		}
		lastPreviewPipelines = pipelines;
		if (parsed.saveStatus === 'unsaved') {
			saveStatus.send('markUnsaved');
		} else {
			saveStatus.send('saveComplete');
		}
		draftLoaded = true;
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!storageKey || !draftLoaded) return;
		if (!analysisStore.tabs.length) return;
		const payload = {
			analysisId,
			tabs: analysisStore.tabs,
			activeTabId: analysisStore.activeTabId,
			resourceConfig: analysisStore.resourceConfig,
			engineDefaults: analysisStore.engineDefaults,
			previewVersions: Object.fromEntries(previewVersions.entries()),
			lastPreviewPipelines: Object.fromEntries(lastPreviewPipelines.entries()),
			selectedStepId,
			leftPaneCollapsed,
			rightPaneCollapsed,
			saveStatus: saveStatus.current
		};
		window.localStorage.setItem(storageKey, JSON.stringify(payload));
	});

	type SaveStates = 'saved' | 'unsaved' | 'saving';
	type SaveEvents = 'markUnsaved' | 'startSave' | 'saveComplete' | 'saveError';
	const saveStatus = new FiniteStateMachine<SaveStates, SaveEvents>('saved', {
		saved: { markUnsaved: 'unsaved', saveComplete: 'saved' },
		unsaved: { markUnsaved: 'unsaved', startSave: 'saving' },
		saving: { saveComplete: 'saved', saveError: 'unsaved' }
	});
	let isLoadingSchema = $state(false);
	let showDatasourceModal = $state(false);
	let modalMode = $state<'add' | 'change'>('add');
	let leftPaneCollapsed = $state(false);
	let rightPaneCollapsed = $state(false);

	const analysisQuery = createQuery(() => ({
		queryKey: ['analysis', analysisId],
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			const result = await getAnalysis(analysisId);
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			await analysisStore.loadAnalysis(analysisId);
			saveStatus.send('saveComplete');
			return result.value;
		},
		retry: false
	}));

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

	// Update datasourceStore when query data changes
	$effect(() => {
		const data = datasourcesQuery.data;
		if (data) {
			datasourceStore.datasources = data;
		}
	});

	// All available datasources (filtering handled by modal component)
	const filteredDatasources = $derived(datasourcesQuery.data ?? []);

	// Spawn engine on load to get defaults
	$effect(() => {
		if (!analysisId || analysisStore.engineDefaults) return;
		spawnEngine(analysisId).match(
			(status) => {
				if (status.defaults) {
					analysisStore.setEngineDefaults(status.defaults);
				}
			},
			() => {} // Ignore errors, defaults just won't be shown
		);
	});

	$effect(() => {
		const datasourceIdValue = datasourceId;
		if (!datasourceIdValue) return;

		const existingSchema = analysisStore.sourceSchemas.get(datasourceIdValue);
		if (existingSchema) return;

		isLoadingSchema = true;
		getDatasourceSchema(datasourceIdValue).match(
			(schema) => {
				analysisStore.setSourceSchema(datasourceIdValue, schema);
				isLoadingSchema = false;
			},
			(err) => {
				console.error('Failed to load schema:', err);
				isLoadingSchema = false;
			}
		);
	});

	// Use active tab's datasource
	const datasourceId = $derived(analysisStore.activeTab?.datasource_id ?? undefined);
	const savedSteps = $derived.by(() => {
		const activeTab = analysisStore.activeTab;
		if (!activeTab) return [];
		const savedTab = analysisStore.savedTabs.find((tab) => tab.id === activeTab.id);
		return savedTab?.steps ?? [];
	});
	const previewDatasourceId = $derived.by(() => {
		const activeTab = analysisStore.activeTab;
		if (!activeTab) return undefined;
		const savedTab = analysisStore.savedTabs.find((tab) => tab.id === activeTab.id);
		return savedTab?.datasource_id ?? undefined;
	});

	// Get the current datasource object for the active tab
	const currentDatasource = $derived.by(() => {
		if (!datasourceId) return null;
		const data = datasourcesQuery.data;
		if (!data) return null;
		return data.find((ds) => ds.id === datasourceId) ?? null;
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
			config: getDefaultConfig(type) as Record<string, unknown>,
			depends_on: []
		};
	}

	function markUnsaved() {
		saveStatus.send('markUnsaved');
	}

	function handleAddStep(type: string) {
		const step = buildStep(type);
		analysisStore.addStep(step);
		selectedStepId = step.id;
		markUnsaved();
	}

	function handleInsertStep(type: string, target: DropTarget) {
		const step = buildStep(type);
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			selectedStepId = step.id;
			markUnsaved();
		}
	}

	function handleMoveStep(stepId: string, target: DropTarget) {
		analysisStore.moveStep(stepId, target.index, target.parentId, target.nextId);
		markUnsaved();
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
	}

	function handleDeleteStep(stepId: string) {
		analysisStore.removeStep(stepId);
		if (selectedStepId === stepId) {
			selectedStepId = null;
		}
		markUnsaved();
	}

	async function handleSave() {
		if (isSaving || saveStatus.current === 'saving') return;

		isSaving = true;
		saveStatus.send('startSave');

		analysisStore.save().match(
			() => {
				saveStatus.send('saveComplete');
				selectedStepId = null;
				isSaving = false;

				// Reset engine idle timeout on successful save
				if (analysisId) {
					setTimeout(() => {
						sendKeepalive(analysisId);
					}, 1000);
				}
			},
			(error) => {
				saveStatus.send('saveError');
				alert(`Failed to save pipeline: ${error.message}`);
				isSaving = false;
			}
		);
	}

	function handleCloseConfig() {
		selectedStepId = null;
	}

	function handleSelectTab(tabId: string) {
		analysisStore.setActiveTab(tabId);
		saveStatus.send('saveComplete');
	}

	function handleAddTab(datasourceId: string, name: string) {
		const tab: AnalysisTab = {
			id: `tab-${datasourceId}-${Date.now()}`,
			name,
			type: 'datasource',
			parent_id: null,
			datasource_id: datasourceId,
			steps: []
		};
		analysisStore.addTab(tab);
		analysisStore.setActiveTab(tab.id);
		showDatasourceModal = false;
		markUnsaved();
	}

	function handleChangeDatasource(datasourceId: string, name: string) {
		const active = analysisStore.activeTab;
		if (!active) return;
		analysisStore.updateTab(active.id, { datasource_id: datasourceId, name });
		showDatasourceModal = false;
		markUnsaved();
	}

	function handleDatasourceSelect(datasourceId: string, name: string) {
		if (modalMode === 'change') {
			handleChangeDatasource(datasourceId, name);
		} else {
			handleAddTab(datasourceId, name);
		}
	}

	function handleRemoveTab(tabId: string) {
		analysisStore.removeTab(tabId);
		markUnsaved();
	}

	function handleRenameSourceTab(nextName: string) {
		const active = analysisStore.activeTab;
		if (!active) return;
		const trimmed = nextName.trim();
		if (!trimmed || trimmed === active.name) return;
		analysisStore.updateTab(active.id, { name: trimmed });
		markUnsaved();
	}

	function openDatasourceModal(mode: 'add' | 'change' = 'add') {
		modalMode = mode;
		showDatasourceModal = true;
	}

	function closeDatasourceModal() {
		showDatasourceModal = false;
	}
</script>

{#if analysisQuery.isLoading}
	<div class="info-box loading-container">
		<div class="spinner"></div>
		<p>Loading analysis...</p>
	</div>
{:else if analysisQuery.isError}
	<div class="error-box error-container">
		<div class="error-icon">!</div>
		<h2>Error loading analysis</h2>
		<p>{analysisQuery.error instanceof Error ? analysisQuery.error.message : 'Unknown error'}</p>
		<button
			class="btn-primary"
			onclick={() => goto(resolve('/'), { invalidateAll: true })}
			type="button">Back to Gallery</button
		>
	</div>
{:else if analysisQuery.data}
	<div class="editor-container">
		<header class="editor-header">
			<div class="header-left">
				<div class="analysis-name">
					<h1
						contenteditable="true"
						class="editable-title"
						onblur={(e) => {
							const newName = e.currentTarget.textContent?.trim();
							if (newName && newName !== analysisQuery.data.name) {
								analysisStore.update({ name: newName });
								markUnsaved();
							} else if (e.currentTarget) {
								e.currentTarget.textContent = analysisQuery.data.name;
							}
						}}
					>
						{analysisQuery.data.name}
					</h1>
					{#if analysisQuery.data.description}
						<span class="description">{analysisQuery.data.description}</span>
					{/if}
				</div>
				<button
					class="collapse-arrow collapse-arrow-left"
					class:collapsed={leftPaneCollapsed}
					onclick={() => (leftPaneCollapsed = !leftPaneCollapsed)}
					type="button"
					title={leftPaneCollapsed ? 'Expand operations' : 'Collapse operations'}
				>
					{leftPaneCollapsed ? '‹' : '›'}
				</button>
			</div>
			<div class="header-middle">
				<div class="header-tabs">
					<div class="tabs">
						{#each analysisStore.tabs.filter((t) => t.type === 'datasource') as tab (tab.id)}
							<button
								class="tab"
								class:active={analysisStore.activeTab?.id === tab.id}
								onclick={() => handleSelectTab(tab.id)}
								type="button"
							>
								<span class="tab-label">
									<span class="tab-name">{tab.name}</span>
								</span>
								{#if analysisStore.tabs.length > 1}
									<span
										class="tab-remove"
										onclick={(e) => {
											e.stopPropagation();
											handleRemoveTab(tab.id);
										}}
										role="button"
										tabindex="0"
										onkeydown={(e) => e.key === 'Enter' && handleRemoveTab(tab.id)}
									>
										&times;
									</span>
								{/if}
							</button>
						{/each}
						<button class="tab add-tab" onclick={() => openDatasourceModal('add')} type="button">
							+
						</button>
					</div>
				</div>
			</div>
			<div class="header-right">
				<button
					class="collapse-arrow collapse-arrow-right"
					class:collapsed={rightPaneCollapsed}
					onclick={() => (rightPaneCollapsed = !rightPaneCollapsed)}
					type="button"
					title={rightPaneCollapsed ? 'Expand configuration' : 'Collapse configuration'}
				>
					{rightPaneCollapsed ? '›' : '‹'}
				</button>
				<button class="preview-button" onclick={handlePreview} type="button"> Preview </button>
				<button
					class="save-button"
					class:saved={saveStatus.current === 'saved'}
					class:unsaved={saveStatus.current === 'unsaved'}
					onclick={handleSave}
					disabled={isSaving || saveStatus.current === 'saving' || analysisStore.loading}
					type="button"
				>
					{saveStatus.current === 'saving'
						? 'Saving...'
						: saveStatus.current === 'saved'
							? 'Saved'
							: 'Save'}
				</button>
			</div>
		</header>

		<div class="editor-workspace" role="application">
			<div class="left-pane" class:collapsed={leftPaneCollapsed}>
				<StepLibrary onAddStep={handleAddStep} onInsertStep={handleInsertStep} />
			</div>

			<div class="center-pane">
				<PipelineCanvas
					steps={analysisStore.pipeline}
					{previewDatasourceId}
					{previewVersion}
					{isPreviewStale}
					{analysisId}
					{datasourceId}
					datasource={currentDatasource}
					tabName={analysisStore.activeTab?.name}
					onStepClick={handleSelectStep}
					onStepDelete={handleDeleteStep}
					onInsertStep={handleInsertStep}
					onMoveStep={handleMoveStep}
					onChangeDatasource={() => openDatasourceModal('change')}
					onRenameTab={handleRenameSourceTab}
				/>
			</div>

			<div class="right-pane" class:collapsed={rightPaneCollapsed}>
				<StepConfig
					step={selectedStepState}
					schema={analysisStore.calculatedSchema}
					{isLoadingSchema}
					onClose={handleCloseConfig}
					onConfigChange={markUnsaved}
				/>
			</div>
		</div>
	</div>
{/if}

<DatasourceSelectorModal
	show={showDatasourceModal}
	datasources={datasourcesQuery.data ?? []}
	isLoading={datasourcesQuery.isLoading}
	mode={modalMode}
	onSelect={handleDatasourceSelect}
	onClose={closeDatasourceModal}
/>

<DragPreview />

<style>
	.loading-container,
	.error-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: calc(100vh - 60px);
		gap: var(--space-4);
		text-align: center;
	}

	.spinner {
		width: 32px;
		height: 32px;
		border: 2px solid var(--border-primary);
		border-top-color: var(--fg-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	.loading-container p {
		margin: 0;
	}

	.error-icon {
		width: 52px;
		height: 52px;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		font-size: var(--text-xl);
		font-weight: var(--font-bold);
		box-shadow: var(--shadow-soft);
	}

	.error-container h2,
	.error-container p {
		margin: 0;
	}
	.error-container button {
		margin-top: var(--space-4);
	}

	.editor-container {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 60px);
		background-color: var(--bg-secondary);
	}

	.editor-header {
		display: flex;
		align-items: stretch;
		border-bottom: 1px solid var(--panel-border);
		background-color: var(--panel-bg);
		height: 48px;
	}

	.header-left {
		display: flex;
		align-items: center;
		width: var(--operations-panel-width, 280px);
		height: 100%;
		border-right: 1px solid var(--panel-border);
		transition: width var(--transition);
	}

	.header-middle {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0 var(--space-4);
	}

	.header-right {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		width: var(--operations-panel-width, 280px);
		height: 100%;
		border-left: 1px solid var(--panel-border);
		transition: width var(--transition);
	}

	.analysis-name {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
		overflow: hidden;
		padding: 0 var(--space-4);
	}

	.editable-title {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--font-semibold);
		letter-spacing: 0.02em;
		text-transform: uppercase;
		color: var(--fg-primary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		outline: none;
		cursor: text;
	}

	.editable-title:focus {
		background-color: var(--bg-hover);
		border-radius: var(--radius-sm);
		padding: 0 var(--space-1);
		margin: 0 calc(var(--space-1) * -1);
	}

	.description {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		letter-spacing: 0.02em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.collapse-arrow {
		width: 24px;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--fg-muted);
		font-size: var(--text-lg);
		cursor: pointer;
		transition: color var(--transition);
		flex-shrink: 0;
	}

	.collapse-arrow:hover {
		color: var(--fg-primary);
	}
	.collapse-arrow-left {
		border-left: 1px solid var(--panel-border);
	}
	.collapse-arrow-right {
		border-right: 1px solid var(--panel-border);
	}

	.save-button,
	.preview-button {
		flex: 1;
		height: 100%;
		padding: 0 var(--space-4);
		background: none;
		border: none;
		font-size: var(--text-sm);
		font-weight: var(--font-medium);
		cursor: pointer;
		transition: all var(--transition);
	}

	.save-button.saved {
		color: var(--success-fg);
	}
	.save-button.unsaved {
		background-color: var(--warning-bg);
		color: var(--warning-fg);
		border-left: 1px solid var(--warning-border);
	}
	.save-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.preview-button {
		border-right: 1px solid var(--panel-border);
		color: var(--fg-secondary);
	}
	.preview-button:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}

	.header-tabs {
		overflow: hidden;
		flex: 1;
		display: flex;
		align-items: center;
	}

	.tabs {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		overflow-x: auto;
		width: 100%;
	}

	.tab {
		padding: var(--space-1) var(--space-2);
		background: none;
		border: none;
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--fg-muted);
		font-weight: var(--font-medium);
		transition: all var(--transition);
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		border-radius: var(--radius-sm);
	}

	.tab:hover {
		color: var(--fg-secondary);
		background-color: var(--bg-hover);
	}
	.tab.active {
		color: var(--fg-primary);
		background-color: var(--bg-secondary);
	}

	.tab-label {
		display: inline-flex;
		align-items: center;
		min-width: 0;
	}
	.tab-name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 150px;
	}
	.tab-remove {
		margin-left: var(--space-1);
		opacity: 0.5;
		font-size: var(--text-base);
		line-height: 1;
	}
	.tab-remove:hover {
		opacity: 1;
		color: var(--error-fg);
	}
	.add-tab {
		font-weight: var(--font-semibold);
	}

	.editor-workspace {
		display: flex;
		flex: 1;
		overflow: hidden;
		user-select: none;
		background-color: var(--bg-secondary);
	}

	.left-pane,
	.right-pane {
		flex-shrink: 0;
		overflow: hidden;
		display: flex;
		width: var(--operations-panel-width, 280px);
		background-color: var(--panel-bg);
		transition:
			width var(--transition),
			visibility var(--transition);
	}

	.left-pane {
		border-right: 1px solid var(--panel-border);
	}
	.right-pane {
		border-left: 1px solid var(--panel-border);
	}

	.left-pane.collapsed,
	.right-pane.collapsed {
		width: 0;
		border: none;
	}

	.left-pane :global(> *),
	.right-pane :global(> *) {
		width: 100%;
		visibility: visible;
		transition: visibility var(--transition);
	}

	.left-pane.collapsed :global(> *),
	.right-pane.collapsed :global(> *) {
		visibility: hidden;
	}

	.center-pane {
		flex: 1;
		min-width: 200px;
		overflow: hidden;
		display: flex;
		background-color: var(--bg-secondary);
	}
	.center-pane :global(> *) {
		width: 100%;
	}
</style>
