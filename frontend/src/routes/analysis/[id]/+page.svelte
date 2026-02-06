<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { FiniteStateMachine } from 'runed';
	import { MediaQuery } from 'svelte/reactivity';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import {
		acquireLock,
		releaseLock,
		checkLockStatus,
		hasLock
	} from '$lib/stores/lockManager.svelte';
	import { getAnalysis } from '$lib/api/analysis';
	import { getDatasourceSchema, listDatasources } from '$lib/api/datasource';
	import { spawnEngine } from '$lib/api/compute';
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import { getDefaultConfig } from '$lib/utils/step-config-defaults';
	import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
	import type { DropTarget } from '$lib/stores/drag.svelte';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DragPreview from '$lib/components/pipeline/DragPreview.svelte';
	import DatasourceSelectorModal from '$lib/components/common/DatasourceSelectorModal.svelte';

	const analysisId = $derived($page.params.id);

	let selectedStepId = $state<string | null>(null);
	let selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let draftLoaded = $state(false);

	const storageKey = $derived(analysisId ? `analysis-draft:${analysisId}` : null);

	$effect(() => {
		if (!analysisId) return;
		draftLoaded = false;
	});

	$effect(() => {
		if (typeof window === 'undefined') return;
		if (!storageKey || draftLoaded) return;
		if (!analysisStore.tabs.length) return;

		// Only restore draft if we have an active lock (user was in editing mode)
		// If no lock, discard draft and load saved state
		if (!analysisId || !hasLock(analysisId)) {
			// Clear stale draft
			window.localStorage.removeItem(storageKey);
			draftLoaded = true;
			return;
		}

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
		unsaved: { markUnsaved: 'unsaved', startSave: 'saving', saveComplete: 'saved' },
		saving: { saveComplete: 'saved', saveError: 'unsaved' }
	});
	let isLoadingSchema = $state(false);
	let showDatasourceModal = $state(false);
	let modalMode = $state<'add' | 'change'>('add');
	let leftPaneCollapsed = $state(false);
	let rightPaneCollapsed = $state(false);
	let isEditingMode = $state(false);
	let showModeDropdown = $state(false);
	let keepaliveInterval: number | null = null;

	// Responsive: auto-collapse panes on narrow screens
	const isNarrowScreen = new MediaQuery('max-width: 900px');
	const isMobileScreen = new MediaQuery('max-width: 600px');

	// Auto-collapse left pane on narrow screens when entering edit mode
	$effect(() => {
		if (isEditingMode && isNarrowScreen.current && !leftPaneCollapsed) {
			leftPaneCollapsed = true;
		}
	});

	// Auto-collapse right pane on very narrow screens
	$effect(() => {
		if (isEditingMode && isMobileScreen.current && !rightPaneCollapsed) {
			rightPaneCollapsed = true;
		}
	});

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
			// Sync to store in query success instead of effect
			datasourceStore.datasources = result.value;
			return result.value;
		}
	}));

	$effect(() => {
		if (!analysisId || analysisStore.engineDefaults) return;
		spawnEngine(analysisId).match(
			(status) => {
				if (status.defaults) {
					analysisStore.setEngineDefaults(status.defaults);
				}
			},
			() => {}
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

	const datasourceId = $derived(analysisStore.activeTab?.datasource_id ?? undefined);

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
		const base: PipelineStep = {
			id: makeId(),
			type,
			config: getDefaultConfig(type) as Record<string, unknown>,
			depends_on: []
		};
		return { ...base, is_applied: false } as PipelineStep & { is_applied: boolean };
	}

	function markUnsaved() {
		if (saveStatus.current !== 'saving' && isEditingMode) {
			saveStatus.send('markUnsaved');
		}
	}

	function handleAddStep(type: string) {
		if (!isEditingMode) return;
		const step = buildStep(type);
		analysisStore.addStep(step);
		selectedStepId = step.id;
		markUnsaved();
	}

	function handleInsertStep(type: string, target: DropTarget) {
		if (!isEditingMode) return;
		const step = buildStep(type);
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			selectedStepId = step.id;
			markUnsaved();
		}
	}

	function handleMoveStep(stepId: string, target: DropTarget) {
		if (!isEditingMode) return;
		analysisStore.moveStep(stepId, target.index, target.parentId, target.nextId);
		markUnsaved();
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
	}

	function handleDeleteStep(stepId: string) {
		if (!isEditingMode) return;
		analysisStore.removeStep(stepId);
		if (selectedStepId === stepId) {
			selectedStepId = null;
		}
		markUnsaved();
	}

	function handleToggleStep(stepId: string) {
		if (!isEditingMode) return;
		const step = analysisStore.pipeline.find((item) => item.id === stepId);
		if (!step) return;
		const next = (step as PipelineStep & { is_applied?: boolean }).is_applied === false;
		analysisStore.updateStep(stepId, { is_applied: next } as Partial<PipelineStep> & {
			is_applied: boolean;
		});
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

				if (storageKey && typeof window !== 'undefined') {
					window.localStorage.removeItem(storageKey);
				}
			},
			(error) => {
				saveStatus.send('saveError');
				alert(`Failed to save pipeline: ${error.message}`);
				isSaving = false;
			}
		);
	}

	async function setMode(mode: 'editing' | 'viewing') {
		showModeDropdown = false;

		if (!analysisId) return;

		if (mode === 'editing' && !isEditingMode) {
			const success = await acquireLock(analysisId);
			if (success) {
				isEditingMode = true;
				startLockCheck();
			} else {
				alert('This analysis is currently being edited by another user. Please try again later.');
			}
		} else if (mode === 'viewing' && isEditingMode) {
			// Release lock
			await releaseLock(analysisId);
			stopLockCheck();
			isEditingMode = false;

			// Clear draft - unsaved changes are discarded
			if (storageKey && typeof window !== 'undefined') {
				window.localStorage.removeItem(storageKey);
			}

			// Reset to saved state
			if (analysisQuery.data) {
				await analysisStore.loadAnalysis(analysisId);
				saveStatus.send('saveComplete');
			}
		}
	}

	function startLockCheck() {
		if (keepaliveInterval || !analysisId) return;
		keepaliveInterval = window.setInterval(async () => {
			if (isEditingMode && !hasLock(analysisId!)) {
				alert(
					'Your editing session has expired or been taken by another user. Please save your work and reload the page.'
				);
				isEditingMode = false;
				stopLockCheck();
			}
		}, 10000);
	}

	function stopLockCheck() {
		if (keepaliveInterval) {
			window.clearInterval(keepaliveInterval);
			keepaliveInterval = null;
		}
	}

	$effect(() => {
		return () => {
			stopLockCheck();
		};
	});

	$effect(() => {
		if (!analysisId) return;
		checkLockStatus(analysisId);
	});

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
	<div
		class="info-box flex flex-col items-center justify-center text-center gap-4"
		style="height: calc(100vh - 60px);"
	>
		<div class="spinner"></div>
		<p class="m-0">Loading analysis...</p>
	</div>
{:else if analysisQuery.isError}
	<div
		class="error-box flex flex-col items-center justify-center text-center gap-4"
		style="height: calc(100vh - 60px);"
	>
		<div
			class="flex items-center justify-center text-xl font-bold w-[52px] h-[52px] rounded-sm shadow-soft"
		>
			!
		</div>
		<h2 class="m-0">Error loading analysis</h2>
		<p class="m-0">
			{analysisQuery.error instanceof Error ? analysisQuery.error.message : 'Unknown error'}
		</p>
		<button
			class="btn-primary mt-4"
			onclick={() => goto(resolve('/'), { invalidateAll: true })}
			type="button">Back to Gallery</button
		>
	</div>
{:else if analysisQuery.data}
	<div class="flex flex-col bg-secondary" style="height: calc(100vh - 60px);">
		<header
			class="flex items-stretch sticky top-0 h-12 bg-panel border-b border-panel"
			style="z-index: var(--z-header);"
		>
			<div
				class="header-left flex items-center h-full box-border border-r border-panel"
				style="width: var(--operations-panel-width, 280px); transition: width var(--transition);"
			>
				<div class="flex-1 flex flex-col min-w-0 overflow-hidden px-4">
					<h1
						contenteditable="true"
						class="editable-title m-0 text-sm font-semibold uppercase whitespace-nowrap overflow-hidden text-ellipsis outline-none cursor-text text-fg-primary tracking-[0.02em]"
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
						<span
							class="text-xs whitespace-nowrap overflow-hidden text-ellipsis text-fg-muted tracking-[0.02em]"
							>{analysisQuery.data.description}</span
						>
					{/if}
				</div>
			</div>
			<div class="flex-1 min-w-0 overflow-hidden flex items-center justify-center gap-0">
				<button
					class="collapse-arrow collapse-arrow-left w-6 h-full flex items-center justify-center bg-transparent border-none text-lg cursor-pointer flex-shrink-0 text-fg-muted transition-colors duration-[160ms] border-r border-panel hover:text-fg-primary hover:bg-hover"
					class:collapsed={leftPaneCollapsed}
					class:hidden={!isEditingMode}
					onclick={() => (leftPaneCollapsed = !leftPaneCollapsed)}
					type="button"
					title={leftPaneCollapsed ? 'Expand operations' : 'Collapse operations'}
					disabled={!isEditingMode}
				>
					{leftPaneCollapsed ? '>' : '<'}
				</button>
				<div class="flex-1 overflow-hidden flex items-center px-4">
					<div class="tabs flex items-center overflow-x-auto w-full gap-1">
						{#each analysisStore.tabs.filter((t) => t.type === 'datasource') as tab (tab.id)}
							<button
								class="tab inline-flex items-center bg-transparent border-none cursor-pointer text-sm font-medium uppercase px-2 py-1 text-fg-muted transition-all duration-[160ms] gap-1 tracking-[0.06em] rounded-sm hover:text-fg-secondary hover:bg-hover"
								class:active={analysisStore.activeTab?.id === tab.id}
								onclick={() => handleSelectTab(tab.id)}
								type="button"
							>
								<span class="inline-flex items-center min-w-0">
									<span class="whitespace-nowrap overflow-hidden text-ellipsis max-w-[150px]"
										>{tab.name}</span
									>
								</span>
								{#if analysisStore.tabs.length > 1}
									<span
										class="tab-remove text-base leading-none ml-1 opacity-50 hover:opacity-100 hover:text-error"
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
						<button
							class="tab add-tab inline-flex items-center bg-transparent border-none cursor-pointer text-sm font-semibold uppercase px-2 py-1 text-fg-muted transition-all duration-[160ms] gap-1 tracking-[0.06em] rounded-sm hover:text-fg-secondary hover:bg-hover"
							onclick={() => openDatasourceModal('add')}
							type="button"
						>
							+
						</button>
					</div>
				</div>
				<button
					class="collapse-arrow collapse-arrow-right w-6 h-full flex items-center justify-center bg-transparent border-none text-lg cursor-pointer flex-shrink-0 text-fg-muted transition-colors duration-[160ms] border-l border-panel hover:text-fg-primary hover:bg-hover"
					class:collapsed={rightPaneCollapsed}
					class:hidden={!isEditingMode}
					onclick={() => (rightPaneCollapsed = !rightPaneCollapsed)}
					type="button"
					title={rightPaneCollapsed ? 'Expand configuration' : 'Collapse configuration'}
					disabled={!isEditingMode}
				>
					{rightPaneCollapsed ? '<' : '>'}
				</button>
			</div>
			<div
				class="header-right flex items-center justify-end h-full box-border border-l border-panel"
				style="width: var(--operations-panel-width, 280px); transition: width var(--transition);"
			>
				<div class="relative items-center px-4">
					<button
						class="mode-toggle flex items-center cursor-pointer text-sm px-3 py-2 bg-tertiary border border-primary rounded-sm text-fg-secondary gap-2 transition-all duration-[160ms] hover:bg-hover hover:border-secondary"
						onclick={() => (showModeDropdown = !showModeDropdown)}
						type="button"
					>
						{isEditingMode ? 'Editing' : 'Viewing'}
						<span class="text-xs text-fg-muted">▼</span>
					</button>

					{#if showModeDropdown}
						<div
							class="absolute left-0 min-w-[140px] bg-panel border border-panel rounded-sm shadow-soft p-1 z-[100]"
							style="top: calc(100% + 4px);"
						>
							<button
								class="mode-option flex items-center w-full bg-transparent border-none cursor-pointer text-sm text-left gap-2 px-3 py-2 text-fg-secondary rounded-sm transition-colors duration-[160ms] hover:bg-hover"
								onclick={() => setMode('viewing')}
								type="button"
							>
								<span class="font-bold text-accent">{isEditingMode ? '○' : '●'}</span>
								<span>Viewing</span>
							</button>
							<button
								class="mode-option flex items-center w-full bg-transparent border-none cursor-pointer text-sm text-left gap-2 px-3 py-2 text-fg-secondary rounded-sm transition-colors duration-[160ms] hover:bg-hover"
								onclick={() => setMode('editing')}
								type="button"
							>
								<span class="font-bold text-accent">{isEditingMode ? '●' : '○'}</span>
								<span>Editing</span>
							</button>
						</div>
					{/if}
				</div>

				<button
					class="save-button flex-1 h-full bg-transparent border-none text-sm font-medium cursor-pointer transition-all duration-[160ms]"
					class:saved={saveStatus.current === 'saved'}
					class:unsaved={saveStatus.current === 'unsaved'}
					onclick={handleSave}
					disabled={!isEditingMode ||
						isSaving ||
						saveStatus.current === 'saving' ||
						analysisStore.loading}
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

		<div class="flex flex-1 overflow-hidden select-none bg-secondary" role="application">
			{#if isEditingMode}
				<div
					class="left-pane flex-shrink-0 overflow-hidden flex box-border bg-panel border-r border-panel"
					style="width: var(--operations-panel-width, 280px); transition: width var(--transition), visibility var(--transition);"
					class:collapsed={leftPaneCollapsed}
				>
					<StepLibrary onAddStep={handleAddStep} onInsertStep={handleInsertStep} />
				</div>
			{/if}

			<div
				class="center-pane flex-1 min-w-[200px] flex bg-secondary"
				class:readonly={!isEditingMode}
				class:expanded={!isEditingMode}
			>
				<PipelineCanvas
					steps={analysisStore.pipeline}
					{analysisId}
					{datasourceId}
					datasource={currentDatasource}
					tabName={analysisStore.activeTab?.name}
					onStepClick={handleSelectStep}
					onStepDelete={handleDeleteStep}
					onStepToggle={handleToggleStep}
					onInsertStep={handleInsertStep}
					onMoveStep={handleMoveStep}
					onChangeDatasource={() => openDatasourceModal('change')}
					onRenameTab={handleRenameSourceTab}
				/>
			</div>

			{#if isEditingMode}
				<div
					class="right-pane flex-shrink-0 overflow-hidden flex box-border bg-panel border-l border-panel"
					style="width: var(--operations-panel-width, 280px); transition: width var(--transition), visibility var(--transition);"
					class:collapsed={rightPaneCollapsed}
				>
					<StepConfig
						bind:step={selectedStepState}
						schema={analysisStore.calculatedSchema}
						{isLoadingSchema}
						onClose={handleCloseConfig}
						onConfigApply={markUnsaved}
					/>
				</div>
			{/if}
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
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.spinner {
		width: 32px;
		height: 32px;
		border: 2px solid var(--border-primary);
		border-top-color: var(--fg-primary);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	.editable-title:focus {
		background-color: var(--bg-hover);
		border-radius: var(--radius-sm);
		padding: 0 var(--space-1);
		margin: 0 calc(var(--space-1) * -1);
	}
	.collapse-arrow.hidden {
		visibility: hidden;
		pointer-events: none;
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
	.tab.active {
		color: var(--fg-primary);
		background-color: var(--bg-secondary);
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
	.center-pane :global(> *) {
		width: 100%;
	}
	.center-pane.expanded {
		flex: 1;
	}
	.readonly {
		opacity: 0.7;
	}
	.readonly :global(.step-node),
	.readonly :global(.step-button),
	.readonly :global(.drag-handle),
	.readonly :global(.action-btn),
	.readonly :global(.drop-slot),
	.readonly :global(.datasource-node) {
		pointer-events: none !important;
	}
	.header-right :global(.mode-toggle-container),
	.header-right :global(.mode-toggle-container *) {
		pointer-events: auto !important;
		opacity: 1 !important;
	}
</style>
