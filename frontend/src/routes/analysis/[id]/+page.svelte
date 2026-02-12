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
	import { idbGet, idbSet, idbDelete } from '$lib/utils/indexeddb';
	import { track } from '$lib/utils/audit-log';
	import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
	import type { DropTarget } from '$lib/stores/drag.svelte';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DragPreview from '$lib/components/pipeline/DragPreview.svelte';
	import DatasourceSelectorModal from '$lib/components/common/DatasourceSelectorModal.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { ChevronDown, ChevronLeft, ChevronRight, Plus, X } from 'lucide-svelte';

	const analysisId = $derived($page.params.id);
	let lastAnalysisId = $state<string | null>(null);

	let selectedStepId = $state<string | null>(null);
	let selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let draftLoaded = $state(false);
	let isDirty = $state(false);
	let draftTimer: number | null = null;

	const storageKey = $derived(analysisId ? `analysis-draft:${analysisId}` : null);

	$effect(() => {
		if (!analysisId) return;
		if (lastAnalysisId !== analysisId) {
			if (lastAnalysisId && hasLock(lastAnalysisId)) {
				void releaseLock(lastAnalysisId);
			}
			stopLockCheck();
			analysisStore.reset();
			schemaStore.reset();
			selectedStepId = null;
			isEditingMode = false;
			lastAnalysisId = analysisId;
		}
		draftLoaded = false;
	});

	$effect(() => {
		if (!storageKey || draftLoaded) return;
		if (!analysisStore.tabs.length) return;

		// Only restore draft if we have an active lock (user was in editing mode)
		// If no lock, discard draft and load saved state
		if (!analysisId || !hasLock(analysisId)) {
			// Clear stale draft
			void idbDelete(storageKey);
			draftLoaded = true;
			return;
		}

		void idbGet<string>(storageKey).then((raw) => {
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
			isDirty = true;
			draftLoaded = true;
		});
	});

	$effect(() => {
		if (!storageKey || !draftLoaded) return;
		if (!analysisStore.tabs.length) return;
		if (!isEditingMode) return;
		const payload = {
			analysisId,
			tabs: analysisStore.tabs,
			activeTabId: analysisStore.activeTabId,
			resourceConfig: analysisStore.resourceConfig,
			engineDefaults: analysisStore.engineDefaults,
			selectedStepId,
			leftPaneCollapsed,
			rightPaneCollapsed
		};
		if (draftTimer) window.clearTimeout(draftTimer);
		draftTimer = window.setTimeout(() => {
			void idbSet(storageKey, JSON.stringify(payload));
		}, 400);
	});

	$effect(() => {
		if (!analysisId) return;
		if (!isEditingMode) return;
		isDirty = analysisStore.isDirty();
	});
	let isLoadingSchema = $state(false);
	const HEARTBEAT_INTERVAL_MS = 10000;
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
			analysisStore.applyAnalysis(result.value);
			isDirty = false;
			return result.value;
		},
		staleTime: 0,
		refetchOnMount: 'always',
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
			(err) => {
				track({
					event: 'engine_error',
					action: 'spawn',
					target: analysisId,
					meta: { message: err.message }
				});
			}
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
				track({
					event: 'schema_error',
					action: 'load',
					target: datasourceIdValue,
					meta: { message: err.message }
				});
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
		if (!isEditingMode) return;
		isDirty = true;
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
		if (isSaving) return;

		isSaving = true;

		analysisStore.save().match(
			() => {
				isDirty = false;
				selectedStepId = null;
				isSaving = false;

				if (storageKey) {
					void idbDelete(storageKey);
				}
			},
			(error) => {
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
			if (storageKey) {
				void idbDelete(storageKey);
			}

			// Reset to saved state
			if (analysisQuery.data) {
				const currentTabId = analysisStore.activeTabId;
				await analysisStore.loadAnalysis(analysisId);
				// Restore the tab that was active before switching to viewing mode
				if (currentTabId && analysisStore.tabs.some((t) => t.id === currentTabId)) {
					analysisStore.activeTabId = currentTabId;
				}
				isDirty = false;
			}
		}
	}

	async function discardChanges() {
		showModeDropdown = false;
		if (!analysisId) return;
		if (isSaving) return;
		if (storageKey) {
			void idbDelete(storageKey);
		}
		if (analysisQuery.data) {
			const currentTabId = analysisStore.activeTabId;
			await analysisStore.loadAnalysis(analysisId);
			// Restore the tab that was active before discarding changes
			if (currentTabId && analysisStore.tabs.some((t) => t.id === currentTabId)) {
				analysisStore.activeTabId = currentTabId;
			}
			isDirty = false;
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
		}, HEARTBEAT_INTERVAL_MS);
	}

	function stopLockCheck() {
		if (keepaliveInterval) {
			window.clearInterval(keepaliveInterval);
			keepaliveInterval = null;
		}
	}

	$effect(() => {
		return () => {
			if (analysisId && hasLock(analysisId)) {
				void releaseLock(analysisId);
			}
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
	<div class="flex h-full items-center justify-center">
		<div class="spinner"></div>
	</div>
{:else if analysisQuery.isError}
	<div class="error-box flex h-full flex-col items-center justify-center text-center gap-4">
		<div
			class="flex items-center justify-center text-xl font-bold w-13 h-13 border border-tertiary"
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
	<div class="analysis-page flex h-full flex-col bg-secondary">
		<header
			class="analysis-header flex items-stretch sticky top-0 h-12 bg-panel border-y border-tertiary"
		>
			<div
				class="header-left flex items-center h-full box-border border-r border-tertiary panel-width"
			>
				<div class="flex-1 flex flex-col min-w-0 overflow-hidden px-4">
					<h1
						contenteditable={isEditingMode}
						class="editable-title m-0 text-sm font-semibold uppercase whitespace-nowrap overflow-hidden text-ellipsis outline-none text-fg-primary tracking-[0.02em]"
						class:cursor-text={isEditingMode}
						class:cursor-default={!isEditingMode}
						onblur={(e) => {
							if (!isEditingMode) {
								e.currentTarget.textContent = analysisQuery.data.name;
								return;
							}
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
					class="collapse-arrow collapse-arrow-left w-6 h-full flex items-center justify-center bg-transparent border-none text-lg cursor-pointer shrink-0 text-fg-muted border-r border-tertiary hover:text-fg-primary hover:bg-hover"
					class:collapsed={leftPaneCollapsed}
					class:hidden={!isEditingMode}
					onclick={() => (leftPaneCollapsed = !leftPaneCollapsed)}
					type="button"
					title={leftPaneCollapsed ? 'Expand operations' : 'Collapse operations'}
					disabled={!isEditingMode}
				>
					{#if leftPaneCollapsed}
						<ChevronRight size={14} />
					{:else}
						<ChevronLeft size={14} />
					{/if}
				</button>
				<div class="flex-1 overflow-hidden flex items-center px-4">
					<div class="tabs flex items-center overflow-x-auto w-full gap-1">
						{#each analysisStore.tabs.filter((t) => t.type === 'datasource') as tab (tab.id)}
							<div
								class="tab inline-flex items-center bg-transparent border-none text-sm font-medium uppercase px-2 py-1 text-fg-muted gap-1 tracking-[0.06em]"
								class:active={analysisStore.activeTab?.id === tab.id}
							>
								<button
									class="tab-label inline-flex items-center min-w-0 bg-transparent border-none cursor-pointer"
									onclick={() => handleSelectTab(tab.id)}
									type="button"
								>
									<span class="whitespace-nowrap overflow-hidden text-ellipsis max-w-37.5"
										>{tab.name}</span
									>
								</button>
								{#if analysisStore.tabs.length > 1}
									<button
										class="tab-remove text-base leading-none ml-1 opacity-50 hover:opacity-100 hover:text-error"
										onclick={() => handleRemoveTab(tab.id)}
										type="button"
										aria-label="Remove tab"
									>
										<X size={12} />
									</button>
								{/if}
							</div>
						{/each}
						<button
							class="tab add-tab inline-flex items-center bg-transparent border-none cursor-pointer text-sm font-semibold uppercase px-2 py-1 text-fg-muted gap-1 tracking-[0.06em]"
							onclick={() => openDatasourceModal('add')}
							type="button"
						>
							<Plus size={14} />
						</button>
					</div>
				</div>
				<button
					class="collapse-arrow collapse-arrow-right w-6 h-full flex items-center justify-center bg-transparent border-none text-lg cursor-pointer shrink-0 text-fg-muted border-l border-tertiary hover:text-fg-primary hover:bg-hover"
					class:collapsed={rightPaneCollapsed}
					class:hidden={!isEditingMode}
					onclick={() => (rightPaneCollapsed = !rightPaneCollapsed)}
					type="button"
					title={rightPaneCollapsed ? 'Expand configuration' : 'Collapse configuration'}
					disabled={!isEditingMode}
				>
					{#if rightPaneCollapsed}
						<ChevronLeft size={14} />
					{:else}
						<ChevronRight size={14} />
					{/if}
				</button>
			</div>
			<div
				class="header-right flex items-center justify-end h-full box-border border-l border-tertiary panel-width"
			>
				<div class="relative items-center px-1">
					<button
						class="mode-toggle flex items-center cursor-pointer text-sm py-2 bg-tertiary border border-tertiary text-fg-secondary gap-2 hover:bg-hover hover:border-tertiary"
						onclick={() => (showModeDropdown = !showModeDropdown)}
						type="button"
					>
						{isEditingMode ? 'Editing' : 'Viewing'}
						<ChevronDown size={12} class="text-fg-muted" />
					</button>

					{#if showModeDropdown}
						<div
							class="mode-dropdown absolute left-0 min-w-35 bg-panel border border-tertiary p-1 z-100"
						>
							<button
								class="mode-option flex items-center w-full bg-transparent border-none cursor-pointer text-sm text-left gap-2 py-2 text-fg-secondary hover:bg-hover"
								onclick={() => setMode('viewing')}
								type="button"
							>
								{#if isEditingMode}
									<div class="w-4 h-4 rounded-full border-2 border-accent-primary"></div>
								{:else}
									<div class="w-4 h-4 rounded-full bg-accent-primary"></div>
								{/if}
								<span>Viewing</span>
							</button>
							<button
								class="mode-option flex items-center w-full bg-transparent border-none cursor-pointer text-sm text-left gap-2 py-2 text-fg-secondary hover:bg-hover"
								onclick={() => setMode('editing')}
								type="button"
							>
								{#if isEditingMode}
									<div class="w-4 h-4 rounded-full bg-accent-primary"></div>
								{:else}
									<div class="w-4 h-4 rounded-full border-2 border-accent-primary"></div>
								{/if}
								<span>Editing</span>
							</button>
						</div>
					{/if}
				</div>

				<div class="flex h-full flex-1 p-1">
					<button
						class="cancel-button flex-1 h-full bg-tertiary border-none text-sm font-medium cursor-pointer text-fg-secondary hover:bg-hover hover:text-fg-primary"
						onclick={discardChanges}
						disabled={!isEditingMode || !isDirty || isSaving || analysisStore.loading}
						type="button"
					>
						Cancel
					</button>
					<button
						class="save-button flex-1 h-full bg-transparent border-none text-sm font-medium cursor-pointer"
						class:saved={!isDirty}
						class:unsaved={isDirty}
						onclick={handleSave}
						disabled={!isEditingMode || isSaving || analysisStore.loading}
						type="button"
					>
						{isSaving ? 'Saving...' : isDirty ? 'Save' : 'Saved'}
					</button>
				</div>
			</div>
		</header>

		<div class="flex flex-1 overflow-hidden select-none bg-secondary" role="application">
			{#if isEditingMode}
				<div
					class="left-pane shrink-0 overflow-hidden flex h-full box-border bg-panel border-r border-tertiary panel-width"
					class:collapsed={leftPaneCollapsed}
				>
					<StepLibrary onAddStep={handleAddStep} onInsertStep={handleInsertStep} />
				</div>
			{/if}

			<div
				class="center-pane flex-1 min-w-50 flex bg-secondary"
				class:readonly={!isEditingMode}
				class:expanded={!isEditingMode}
			>
				<PipelineCanvas
					steps={analysisStore.pipeline}
					{analysisId}
					{datasourceId}
					datasource={currentDatasource}
					tabName={analysisStore.activeTab?.name}
					activeTab={analysisStore.activeTab}
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
					class="right-pane shrink-0 overflow-hidden flex h-full box-border bg-panel border-l border-tertiary panel-width"
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
