<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { PersistedState, Debounced, FiniteStateMachine, onClickOutside } from 'runed';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { engineLifecycle } from '$lib/stores/engine-lifecycle.svelte';
	import { getAnalysis } from '$lib/api/analysis';
	import { getDatasourceSchema, listDatasources } from '$lib/api/datasource';
	import { ArrowLeft, FileSpreadsheet, FileJson, FileType, Database, Globe } from 'lucide-svelte';
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import type { DropTarget } from '$lib/stores/drag.svelte';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DragPreview from '$lib/components/pipeline/DragPreview.svelte';

	const analysisId = $derived($page.params.id);

	let selectedStepId = $state<string | null>(null);
	let selectedStepState = $state<PipelineStep | null>(null);
	let isSaving = $state(false);
	type SaveStates = 'saved' | 'unsaved' | 'saving';
	type SaveEvents = 'markUnsaved' | 'startSave' | 'saveComplete' | 'saveError';
	const saveStatus = new FiniteStateMachine<SaveStates, SaveEvents>('saved', {
		saved: { markUnsaved: 'unsaved', saveComplete: 'saved' },
		unsaved: { markUnsaved: 'unsaved', startSave: 'saving' },
		saving: { saveComplete: 'saved', saveError: 'unsaved' }
	});
	let isLoadingSchema = $state(false);
	let showDatasourceModal = $state(false);
	let searchQuery = $state('');
	const debouncedSearch = new Debounced(() => searchQuery, 200);
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

	// Start engine when component mounts, stop on unmount
	onMount(() => {
		if (analysisId) {
			engineLifecycle.start(analysisId);
		}
		return () => engineLifecycle.scheduleShutdown();
	});

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

	// Filtered datasources based on search
	const filteredDatasources = $derived.by(() => {
		const data = datasourcesQuery.data;
		if (!data) return [];
		const all = data;
		const query = debouncedSearch.current.toLowerCase().trim();
		if (!query) return all;
		return all.filter((ds) => ds.name.toLowerCase().includes(query));
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
		return { id: makeId(), type, config: {}, depends_on: [] };
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
		selectedStepState = analysisStore.pipeline.find((step) => step.id === stepId) || null;
		markUnsaved();
	}

	function handleDeleteStep(stepId: string) {
		analysisStore.removeStep(stepId);
		if (selectedStepId === stepId) {
			selectedStepId = null;
			selectedStepState = null;
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
				selectedStepState = null;
				isSaving = false;
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
		selectedStepState = null;
	}

	function handleSelectTab(tabId: string) {
		analysisStore.setActiveTab(tabId);
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
		searchQuery = '';
		markUnsaved();
	}

	function handleChangeDatasource(datasourceId: string, name: string) {
		const active = analysisStore.activeTab;
		if (!active) return;
		analysisStore.updateTab(active.id, { datasource_id: datasourceId, name });
		showDatasourceModal = false;
		searchQuery = '';
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
		searchQuery = '';
		showDatasourceModal = true;
	}

	function closeDatasourceModal() {
		showDatasourceModal = false;
		searchQuery = '';
	}

	let modalRef = $state<HTMLElement>();
	onClickOutside(
		() => modalRef,
		() => closeDatasourceModal(),
		{ immediate: true }
	);

	function handleModalKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') closeDatasourceModal();
	}

	$effect(() => {
		if (selectedStepId) {
			const current = analysisStore.pipeline.find((step) => step.id === selectedStepId);
			if (current) {
				selectedStepState = current;
			}
		}
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
		<button onclick={() => goto(resolve('/'), { invalidateAll: true })} type="button"
			>Back to Gallery</button
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

		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div class="editor-workspace" role="application">
			<div class="left-pane" class:collapsed={leftPaneCollapsed}>
				<StepLibrary onAddStep={handleAddStep} onInsertStep={handleInsertStep} />
			</div>

			<div class="center-pane">
				<PipelineCanvas
					steps={analysisStore.pipeline}
					{savedSteps}
					{previewDatasourceId}
					saveStatus={saveStatus.current}
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
					bind:step={selectedStepState}
					schema={analysisStore.calculatedSchema}
					{isLoadingSchema}
					onClose={handleCloseConfig}
					onConfigChange={markUnsaved}
				/>
			</div>
		</div>
	</div>
{/if}

{#if showDatasourceModal}
	<div
		class="modal-backdrop"
		onclick={closeDatasourceModal}
		onkeydown={handleModalKeydown}
		role="presentation"
	>
		<div
			class="modal"
			bind:this={modalRef}
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-labelledby="modal-title"
			tabindex="0"
		>
			<div class="modal-header">
				<h2 id="modal-title">{modalMode === 'change' ? 'Change Datasource' : 'Add Datasource'}</h2>
				<button class="modal-close" onclick={closeDatasourceModal} type="button" aria-label="Close">
					&times;
				</button>
			</div>
			<div class="modal-body">
				<!-- svelte-ignore a11y_autofocus -->
				<input
					type="text"
					class="search-input"
					placeholder="Search datasources..."
					bind:value={searchQuery}
					autofocus
				/>
				<div class="datasource-list">
					{#if datasourcesQuery.isLoading}
						<div class="list-empty">Loading...</div>
					{:else if filteredDatasources.length === 0}
						<div class="list-empty">
							{searchQuery ? 'No matching datasources' : 'No datasources available'}
						</div>
					{:else}
						{#each filteredDatasources as ds (ds.id)}
							{@const fileType =
								ds.source_type === 'file' ? (ds.config?.file_type as string) : null}
							<button
								class="datasource-item"
								onclick={() => handleDatasourceSelect(ds.id, ds.name)}
								type="button"
							>
								<span class="datasource-name">{ds.name}</span>
								<span class="datasource-type">
									{#if fileType === 'csv'}
										<FileSpreadsheet size={12} />
										CSV
									{:else if fileType === 'json'}
										<FileJson size={12} />
										JSON
									{:else if fileType === 'parquet'}
										<FileType size={12} />
										Parquet
									{:else if fileType === 'ndjson'}
										<FileJson size={12} />
										NDJSON
									{:else if fileType === 'excel'}
										<FileSpreadsheet size={12} />
										Excel
									{:else if ds.source_type === 'database'}
										<Database size={12} />
										Database
									{:else if ds.source_type === 'api'}
										<Globe size={12} />
										API
									{:else}
										{ds.source_type}
									{/if}
								</span>
							</button>
						{/each}
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

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
		gap: 0;
	}

	.editor-header {
		display: flex;
		flex-direction: row;
		align-items: stretch;
		padding: 0;
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
		justify-content: center;
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
		text-align: center;
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
		font-weight: 600;
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
		border-right: none;
	}

	.collapse-arrow-right {
		border-right: 1px solid var(--panel-border);
		border-left: none;
	}

	.save-button {
		flex: 1;
		height: 100%;
		padding: 0 var(--space-4);
		background: none;
		border: none;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		font-weight: 500;
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
		flex-wrap: nowrap;
		overflow-x: auto;
		width: 100%;
	}

	.tab {
		padding: var(--space-1) var(--space-2);
		background: none;
		border: none;
		border-bottom: none !important;
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--fg-muted);
		font-family: var(--font-mono);
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
		padding: var(--space-1) var(--space-2);
		font-weight: 600;
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		background-color: var(--overlay-bg);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal {
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		width: 100%;
		max-width: 480px;
		max-height: 80vh;
		display: flex;
		flex-direction: column;
	}

	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-4);
		border-bottom: 1px solid var(--panel-border);
		background-color: var(--panel-header-bg);
	}

	.modal-header h2 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--fg-primary);
	}

	.modal-close {
		background: none;
		border: none;
		font-size: var(--text-xl);
		color: var(--fg-muted);
		cursor: pointer;
		padding: var(--space-1);
		line-height: 1;
	}

	.modal-close:hover {
		color: var(--fg-primary);
	}

	.modal-body {
		padding: var(--space-4);
		overflow-y: auto;
		background-color: var(--panel-bg);
	}

	.search-input {
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background-color: var(--bg-secondary);
		color: var(--fg-primary);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		margin-bottom: var(--space-3);
	}

	.search-input:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.datasource-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-height: 300px;
		overflow-y: auto;
	}

	.datasource-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: var(--space-3);
		background-color: var(--bg-secondary);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		text-align: left;
		font-family: var(--font-mono);
		cursor: pointer;
		transition: all var(--transition);
	}

	.datasource-item:hover {
		background-color: var(--bg-hover);
		border-color: var(--border-tertiary);
	}

	.datasource-name {
		font-size: var(--text-sm);
		letter-spacing: 0.02em;
		color: var(--fg-primary);
	}

	.datasource-type {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.list-empty {
		padding: var(--space-4);
		text-align: center;
		color: var(--fg-muted);
		font-size: var(--text-sm);
	}

	.editor-workspace {
		display: flex;
		flex: 1;
		overflow: hidden;
		user-select: none;
		background-color: var(--bg-secondary);
	}

	.left-pane {
		flex-shrink: 0;
		overflow: hidden;
		display: flex;
		width: var(--operations-panel-width, 280px);
		justify-content: left;
		background-color: var(--panel-bg);
		border-right: 1px solid var(--panel-border);
		transition:
			width var(--transition),
			visibility var(--transition);
	}

	.left-pane.collapsed {
		width: 0;
		border-right: none;
	}

	.left-pane :global(> *) {
		width: 100%;
		visibility: visible;
		transition: visibility var(--transition);
	}

	.left-pane.collapsed :global(> *) {
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

	.right-pane {
		flex-shrink: 0;
		overflow: hidden;
		display: flex;
		width: var(--operations-panel-width, 280px);
		justify-content: left;
		background-color: var(--panel-bg);
		border-left: 1px solid var(--panel-border);
		transition:
			width var(--transition),
			visibility var(--transition);
	}

	.right-pane.collapsed {
		width: 0;
		border-left: none;
	}

	.right-pane :global(> *) {
		width: 100%;
		visibility: visible;
		transition: visibility var(--transition);
	}

	.right-pane.collapsed :global(> *) {
		visibility: hidden;
	}
</style>
