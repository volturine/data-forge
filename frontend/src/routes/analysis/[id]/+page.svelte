<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import { MediaQuery } from 'svelte/reactivity';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { buildAnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
	import {
		acquireLock,
		releaseLock,
		checkLockStatus,
		hasLock
	} from '$lib/stores/lockManager.svelte';
	import {
		getAnalysis,
		listAnalysisVersions,
		restoreAnalysisVersion,
		renameAnalysisVersion
	} from '$lib/api/analysis';
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
	import { ChevronDown, ChevronLeft, ChevronRight, Pencil, Plus, X } from 'lucide-svelte';

	const analysisId = $derived($page.params.id ?? null);
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
	let modalSource = $state<'datasource' | 'analysis'>('datasource');
	let leftPaneCollapsed = $state(false);
	let rightPaneCollapsed = $state(false);
	let isEditingMode = $state(false);
	let showModeDropdown = $state(false);
	let showVersionModal = $state(false);
	let versionError = $state<string | null>(null);
	let editingVersionId = $state<string | null>(null);
	let editingVersionName = $state('');
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

	const versionsQuery = createQuery(() => ({
		queryKey: ['analysis-versions', analysisId],
		enabled: false,
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			const result = await listAnalysisVersions(analysisId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const analysisTabs = $derived.by(() => {
		const title = analysisStore.current?.name ?? analysisQuery.data?.name ?? 'Analysis';
		return analysisStore.tabs.map((tab) => ({
			id: tab.id,
			name: `${title} · ${tab.name}`
		}));
	});

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
		const current = datasourcesQuery.data?.find((ds) => ds.id === datasourceIdValue) ?? null;
		const analysisSourceId =
			(analysisStore.activeTab?.datasource_config?.analysis_id as string | null) ??
			(current?.config?.analysis_id as string | null) ??
			null;
		const analysisTabId =
			(analysisStore.activeTab?.datasource_config?.analysis_tab_id as string | null) ??
			(current?.config?.analysis_tab_id as string | null) ??
			null;
		const analysisPayload =
			analysisSourceId && analysisId && analysisSourceId === analysisId
				? buildAnalysisPipelinePayload(analysisId, analysisStore.tabs, datasourceStore.datasources)
				: null;

		if (analysisSourceId) {
			const tabParam = analysisTabId ? `?analysis_tab_id=${encodeURIComponent(analysisTabId)}` : '';
			const body = analysisPayload ? JSON.stringify({ pipeline: analysisPayload }) : undefined;
			void fetch(`/api/v1/analysis/${analysisSourceId}/execute${tabParam}`, {
				method: 'POST',
				body,
				headers: body ? { 'Content-Type': 'application/json' } : undefined
			})
				.then((response) => {
					if (!response.ok) {
						throw new Error('Failed to execute analysis');
					}
					return response.json() as Promise<{
						schema: Record<string, string>;
						rows: Array<Record<string, unknown>>;
						row_count?: number;
					}>;
				})
				.then((payload) => {
					const columns = Object.entries(payload.schema).map(([name, dtype]) => ({
						name,
						dtype: String(dtype),
						nullable: true
					}));
					analysisStore.setSourceSchema(datasourceIdValue, {
						columns,
						row_count: payload.row_count ?? payload.rows.length
					});
					isLoadingSchema = false;
				})
				.catch((error: unknown) => {
					const message = error instanceof Error ? error.message : 'Failed to execute analysis';
					track({
						event: 'schema_error',
						action: 'analysis_source_schema',
						target: analysisSourceId,
						meta: { message }
					});
					isLoadingSchema = false;
				});
			return;
		}

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

	function buildInitialSteps(): PipelineStep[] {
		const step = buildStep('view');
		step.depends_on = [];
		return [step];
	}

	function handleAddTab(datasourceId: string, name: string) {
		const tab: AnalysisTab = {
			id: `tab-${datasourceId}-${Date.now()}`,
			name,
			type: 'datasource',
			parent_id: null,
			datasource_id: datasourceId,
			steps: buildInitialSteps()
		};
		analysisStore.addTab(tab);
		analysisStore.setActiveTab(tab.id);
		showDatasourceModal = false;
		markUnsaved();
	}

	function handleAddAnalysisTab(
		datasourceId: string,
		sourceAnalysisId: string,
		name: string,
		sourceTabId: string | null
	) {
		if (
			modalMode === 'change' &&
			analysisId &&
			sourceAnalysisId === analysisId &&
			sourceTabId === analysisStore.activeTabId
		) {
			alert('Select a different tab to avoid using the current tab as its own source.');
			return;
		}
		const tab: AnalysisTab = {
			id: `tab-analysis-${datasourceId}-${Date.now()}`,
			name,
			type: 'datasource',
			parent_id: null,
			datasource_id: datasourceId,
			datasource_config: sourceTabId
				? { analysis_id: sourceAnalysisId, analysis_tab_id: sourceTabId }
				: { analysis_id: sourceAnalysisId },
			steps: buildInitialSteps()
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

	function handleDatasourceSelect(
		datasourceId: string,
		name: string,
		source: 'datasource' | 'analysis'
	) {
		if (source === 'analysis') {
			const analysisTabId = datasourceId;
			const analysisMatch = datasourcesQuery.data?.find((item) => {
				if (item.source_type !== 'analysis') return false;
				if (item.config?.analysis_tab_id !== analysisTabId) return false;
				return String(item.config?.analysis_id ?? '') === String(analysisId ?? '');
			});
			if (analysisMatch) {
				handleAddAnalysisTab(
					analysisMatch.id,
					String(analysisMatch.config?.analysis_id ?? ''),
					name,
					analysisTabId
				);
				return;
			}
			// Defer datasource creation to save — backend update_analysis
			// auto-creates analysis datasources when datasource_id is null
			const tab: AnalysisTab = {
				id: `tab-analysis-${Date.now()}`,
				name,
				type: 'datasource',
				parent_id: null,
				datasource_id: null,
				datasource_config: { analysis_id: analysisId, analysis_tab_id: analysisTabId },
				steps: buildInitialSteps()
			};
			analysisStore.addTab(tab);
			analysisStore.setActiveTab(tab.id);
			showDatasourceModal = false;
			markUnsaved();
			return;
		}
		if (modalMode === 'change') {
			handleChangeDatasource(datasourceId, name);
			return;
		}
		handleAddTab(datasourceId, name);
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
		modalSource = 'datasource';
		showDatasourceModal = true;
	}

	function closeDatasourceModal() {
		showDatasourceModal = false;
	}

	function openVersionModal() {
		showModeDropdown = false;
		versionError = null;
		showVersionModal = true;
		versionsQuery.refetch().catch(() => {
			versionError = 'Failed to load version history';
		});
	}

	function closeVersionModal() {
		showVersionModal = false;
		versionError = null;
	}

	function handleVersionKeydown(event: KeyboardEvent) {
		if (!showVersionModal) return;
		if (event.key !== 'Escape') return;
		closeVersionModal();
	}

	function formatVersionDate(value: string | null | undefined): string {
		if (!value) return 'Unknown';
		const parsed = new Date(value);
		if (Number.isNaN(parsed.getTime())) return 'Unknown';
		return parsed.toLocaleString();
	}

	async function handleRestoreVersion(version: number) {
		if (!analysisId) return;
		versionError = null;
		const result = await restoreAnalysisVersion(analysisId, version);
		if (result.isErr()) {
			versionError = result.error.message;
			return;
		}
		analysisStore.applyAnalysis(result.value);
		showVersionModal = false;
		isDirty = false;
	}

	function startRenameVersion(id: string, name: string) {
		editingVersionId = id;
		editingVersionName = name;
	}

	async function commitRenameVersion(version: number) {
		if (!analysisId || !editingVersionId) return;
		const trimmed = editingVersionName.trim();
		if (!trimmed) {
			editingVersionId = null;
			return;
		}
		const result = await renameAnalysisVersion(analysisId, version, trimmed);
		if (result.isErr()) {
			versionError = result.error.message;
		} else {
			versionsQuery.refetch();
		}
		editingVersionId = null;
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
						<div class="flex items-center gap-1">
							<button
								class="tab add-tab inline-flex items-center bg-transparent border-none cursor-pointer text-sm font-semibold uppercase px-2 py-1 text-fg-muted gap-1 tracking-[0.06em]"
								onclick={() => openDatasourceModal('add')}
								type="button"
								title="Add datasource tab"
							>
								<Plus size={14} />
							</button>
						</div>
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
				<div class="mode-toggle-container relative items-center px-1">
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
							<button
								class="mode-option flex items-center w-full bg-transparent border-none cursor-pointer text-sm text-left gap-2 py-2 text-fg-secondary hover:bg-hover"
								onclick={openVersionModal}
								type="button"
							>
								<div class="w-4 h-4 rounded-full border-2 border-accent-primary"></div>
								<span>Rollback</span>
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
					analysisId={analysisId ?? undefined}
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

<svelte:window onkeydown={handleVersionKeydown} />

<DatasourceSelectorModal
	show={showDatasourceModal}
	datasources={datasourcesQuery.data ?? []}
	isLoading={datasourcesQuery.isLoading}
	mode={modalMode}
	sourceType={modalSource}
	{analysisTabs}
	excludeTabId={analysisStore.activeTabId}
	onSelect={handleDatasourceSelect}
	onClose={closeDatasourceModal}
/>

{#if showVersionModal}
	<div class="modal-backdrop" aria-hidden="true"></div>
	<div class="modal" role="dialog" aria-modal="true" aria-labelledby="analysis-version-title">
		<div class="modal-header">
			<h2 id="analysis-version-title">Version history</h2>
			<button class="modal-close" onclick={closeVersionModal} aria-label="Close">
				<X size={16} />
			</button>
		</div>
		<div class="modal-body">
			{#if versionError}
				<div class="error-box m-0">
					{versionError}
				</div>
			{/if}
			{#if versionsQuery.isLoading}
				<div class="flex items-center justify-center p-8 text-sm text-fg-muted">Loading...</div>
			{:else if versionsQuery.isError}
				<div class="error-box m-0">Failed to load version history.</div>
			{:else if !versionsQuery.data?.length}
				<p class="empty-message">No versions available.</p>
			{:else}
				<div class="flex flex-col gap-2">
					{#each versionsQuery.data as version (version.id)}
						<div
							class="flex items-start justify-between gap-4 border border-tertiary bg-tertiary p-3"
						>
							<div class="flex min-w-0 flex-col gap-1">
								<div class="text-[0.65rem] uppercase tracking-[0.1em] text-fg-muted">
									Version {version.version} · {formatVersionDate(version.created_at)}
								</div>
								{#if editingVersionId === version.id}
									<input
										type="text"
										class="text-sm font-semibold text-fg-primary bg-transparent border border-tertiary px-1 py-0.5 w-full"
										bind:value={editingVersionName}
										onblur={() => commitRenameVersion(version.version)}
										onkeydown={(e) => {
											if (e.key === 'Enter') commitRenameVersion(version.version);
											if (e.key === 'Escape') editingVersionId = null;
										}}
									/>
								{:else}
									<div class="flex items-center gap-1.5">
										<span class="text-sm font-semibold text-fg-primary">
											{version.name}
										</span>
										<button
											class="p-0.5 bg-transparent border-transparent text-fg-muted hover:text-fg-primary"
											title="Rename version"
											onclick={() => startRenameVersion(version.id, version.name)}
										>
											<Pencil size={12} />
										</button>
									</div>
								{/if}
								{#if version.description}
									<div class="text-xs text-fg-muted">{version.description}</div>
								{/if}
							</div>
							<button
								class="btn-secondary btn-sm shrink-0"
								onclick={() => handleRestoreVersion(version.version)}
								type="button"
							>
								Restore
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>
		<div class="modal-footer">
			<button class="btn-secondary" onclick={closeVersionModal}>Close</button>
		</div>
	</div>
{/if}

<DragPreview />
