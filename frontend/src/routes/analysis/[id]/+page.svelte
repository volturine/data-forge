<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { getAnalysis } from '$lib/api/analysis';
	import { getDatasourceSchema, listDatasources } from '$lib/api/datasource';
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import type { DropTarget } from '$lib/stores/drag.svelte';
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
	let showDatasourceModal = $state(false);
	let searchQuery = $state('');
	let editingTabId = $state<string | null>(null);
	let editingTabName = $state('');

	// Resizable panes
	let leftPaneWidth = $state(240);
	let rightPaneWidth = $state(320);
	let isResizingLeft = $state(false);
	let isResizingRight = $state(false);

	function startResizeLeft(e: MouseEvent) {
		isResizingLeft = true;
		e.preventDefault();
	}

	function startResizeRight(e: MouseEvent) {
		isResizingRight = true;
		e.preventDefault();
	}

	function handleMouseMove(e: MouseEvent) {
		if (isResizingLeft) {
			const newWidth = e.clientX;
			leftPaneWidth = Math.max(180, Math.min(400, newWidth));
		} else if (isResizingRight) {
			const newWidth = window.innerWidth - e.clientX;
			rightPaneWidth = Math.max(250, Math.min(500, newWidth));
		}
	}

	function stopResize() {
		isResizingLeft = false;
		isResizingRight = false;
	}

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

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources'],
		queryFn: listDatasources
	}));

	// Filtered datasources based on search
	const filteredDatasources = $derived.by(() => {
		const all = datasourcesQuery.data ?? [];
		const query = searchQuery.toLowerCase().trim();
		if (!query) return all;
		return all.filter((ds) => ds.name.toLowerCase().includes(query));
	});

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

	// Use active tab's datasource
	const datasourceId = $derived(analysisStore.activeTab?.datasource_id ?? undefined);

	function makeId() {
		if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
			return crypto.randomUUID();
		}
		return 'id-' + Math.random().toString(16).slice(2) + Date.now().toString(16);
	}

	function buildStep(type: string): PipelineStep {
		return { id: makeId(), type, config: {}, depends_on: [] };
	}

	function handleAddStep(type: string) {
		const step = buildStep(type);
		analysisStore.addStep(step);
		selectedStepId = step.id;
	}

	function handleInsertStep(type: string, target: DropTarget) {
		const step = buildStep(type);
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			selectedStepId = step.id;
		}
	}

	function handleMoveStep(stepId: string, target: DropTarget) {
		analysisStore.moveStep(stepId, target.index, target.parentId, target.nextId);
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
	}

	function handleRemoveTab(tabId: string) {
		analysisStore.removeTab(tabId);
	}

	function startRenameTab(tab: AnalysisTab) {
		editingTabId = tab.id;
		editingTabName = tab.name;
	}

	function cancelRenameTab() {
		editingTabId = null;
		editingTabName = '';
	}

	function scheduleSave() {
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
	}

	function commitRenameTab(tab: AnalysisTab) {
		const nextName = editingTabName.trim();
		if (!nextName) {
			cancelRenameTab();
			return;
		}
		if (nextName !== tab.name) {
			analysisStore.updateTab(tab.id, { name: nextName });
			scheduleSave();
		}
		cancelRenameTab();
	}

	function openDatasourceModal() {
		searchQuery = '';
		showDatasourceModal = true;
	}

	function closeDatasourceModal() {
		showDatasourceModal = false;
		searchQuery = '';
	}

	function handleModalKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') closeDatasourceModal();
	}

	const selectedStep = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});

	// Auto-save when pipeline changes
	$effect(() => {
		const pipeline = analysisStore.pipeline;

		if (initialPipeline === null) {
			initialPipeline = pipeline;
			return;
		}

		if (pipeline === initialPipeline) return;

		if (saveTimeout) {
			clearTimeout(saveTimeout);
			saveTimeout = null;
		}

		scheduleSave();

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
				{#each analysisStore.tabs.filter((t) => t.type === 'datasource') as tab (tab.id)}
					<button
						class="tab"
						class:active={analysisStore.activeTab?.id === tab.id}
						onclick={() => handleSelectTab(tab.id)}
						type="button"
					>
						<span class="tab-label">
							{#if editingTabId === tab.id}
								<input
									class="tab-rename-input"
									bind:value={editingTabName}
									onclick={(e) => e.stopPropagation()}
									onkeydown={(e) => {
										if (e.key === 'Enter') commitRenameTab(tab);
										if (e.key === 'Escape') cancelRenameTab();
									}}
									onblur={() => commitRenameTab(tab)}
									aria-label="Rename tab"
								/>
							{:else}
								<span class="tab-name">{tab.name}</span>
							{/if}
						</span>
						<span class="tab-actions">
							<span
								class="tab-rename"
								onclick={(e) => {
									e.stopPropagation();
									startRenameTab(tab);
								}}
								role="button"
								tabindex="0"
								onkeydown={(e) => e.key === 'Enter' && startRenameTab(tab)}
								aria-label="Rename tab"
							>
								✎
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
						</span>
					</button>
				{/each}
				<button class="tab add-tab" onclick={openDatasourceModal} type="button"> + </button>
			</div>
		</div>

		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="editor-workspace"
			onmousemove={handleMouseMove}
			onmouseup={stopResize}
			onmouseleave={stopResize}
			role="application"
		>
			<div class="left-pane" style="width: {leftPaneWidth}px">
				<StepLibrary onAddStep={handleAddStep} onInsertStep={handleInsertStep} />
			</div>
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<div
				class="resize-handle"
				onmousedown={startResizeLeft}
				role="separator"
				aria-orientation="vertical"
			></div>
			<div class="center-pane">
				<PipelineCanvas
					steps={analysisStore.pipeline}
					{datasourceId}
					onStepClick={handleSelectStep}
					onStepDelete={handleDeleteStep}
					onInsertStep={handleInsertStep}
					onMoveStep={handleMoveStep}
				/>
			</div>
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<div
				class="resize-handle"
				onmousedown={startResizeRight}
				role="separator"
				aria-orientation="vertical"
			></div>
			<div class="right-pane" style="width: {rightPaneWidth}px">
				<StepConfig
					step={selectedStep}
					schema={analysisStore.calculatedSchema}
					{isLoadingSchema}
					onClose={handleCloseConfig}
				/>
			</div>
		</div>
	</div>
{/if}

{#if showDatasourceModal}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="modal-backdrop"
		onclick={closeDatasourceModal}
		onkeydown={handleModalKeydown}
		role="presentation"
	>
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div
			class="modal"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-labelledby="modal-title"
			tabindex="0"
		>
			<div class="modal-header">
				<h2 id="modal-title">Add Datasource</h2>
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
							<button
								class="datasource-item"
								onclick={() => handleAddTab(ds.id, ds.name)}
								type="button"
							>
								<span class="datasource-name">{ds.name}</span>
								<span class="datasource-type">{ds.source_type}</span>
							</button>
						{/each}
					{/if}
				</div>
			</div>
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
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}

	.tab:hover {
		color: var(--fg-secondary);
	}

	.tab.active {
		color: var(--accent-primary);
		border-bottom-color: var(--accent-primary);
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
		max-width: 180px;
	}

	.tab-rename-input {
		width: 160px;
		max-width: 220px;
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-secondary);
		background-color: var(--bg-secondary);
		color: var(--fg-primary);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}

	.tab-rename-input:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.tab-actions {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}

	.tab-rename {
		color: var(--fg-muted);
		cursor: pointer;
		font-size: var(--text-xs);
		padding: 0;
		line-height: 1;
		opacity: 0.7;
	}

	.tab-rename:hover {
		opacity: 1;
		color: var(--fg-secondary);
	}

	.tab-remove {
		margin-left: var(--space-2);
		opacity: 0.5;
		font-size: var(--text-base);
		line-height: 1;
	}

	.tab-remove:hover {
		opacity: 1;
		color: var(--error-fg);
	}

	.add-tab {
		padding: var(--space-2) var(--space-3);
		font-weight: 600;
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		background-color: rgba(0, 0, 0, 0.5);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
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
		border-bottom: 1px solid var(--border-primary);
	}

	.modal-header h2 {
		margin: 0;
		font-size: var(--text-base);
		font-weight: 600;
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
	}

	.search-input {
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--border-secondary);
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
		background: none;
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		text-align: left;
		font-family: var(--font-mono);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.datasource-item:hover {
		background-color: var(--bg-hover);
		border-color: var(--accent-primary);
	}

	.datasource-name {
		font-size: var(--text-sm);
		color: var(--fg-primary);
	}

	.datasource-type {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-transform: uppercase;
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
	}

	.left-pane {
		flex-shrink: 0;
		overflow: hidden;
		display: flex;
		min-width: 330px;
		justify-content: left;
	}

	.left-pane :global(> *) {
		width: 100%;
	}

	.center-pane {
		flex: 1;
		min-width: 200px;
		overflow: hidden;
		display: flex;
	}

	.center-pane :global(> *) {
		width: 100%;
	}

	.right-pane {
		flex-shrink: 0;
		overflow: hidden;
		display: flex;
		min-width: 330px;
		justify-content: left;
	}

	.right-pane :global(> *) {
		width: 100%;
	}

	.resize-handle {
		width: 4px;
		background-color: var(--border-primary);
		cursor: col-resize;
		flex-shrink: 0;
		transition: background-color var(--transition-fast);
	}

	.resize-handle:hover {
		background-color: var(--accent-primary);
	}
</style>
