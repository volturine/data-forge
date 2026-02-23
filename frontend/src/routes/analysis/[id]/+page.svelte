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
		getAnalysisWithHeaders,
		listAnalysisVersions,
		restoreAnalysisVersion,
		renameAnalysisVersion
	} from '$lib/api/analysis';
	import { getDatasourceSchema, listDatasources } from '$lib/api/datasource';
	import { getStepSchema, spawnEngine } from '$lib/api/compute';
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
	import {
		ChevronDown,
		ChevronLeft,
		ChevronRight,
		ChevronUp,
		PanelRight,
		PanelBottom,
		Pencil,
		Plus,
		X
	} from 'lucide-svelte';

	const analysisId = $derived($page.params.id ?? null);
	let lastAnalysisId = $state<string | null>(null);

	let selectedStepId = $state<string | null>(null);
	const selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let draftLoaded = $state(false);
	let isDirty = $state(false);
	let draftTimer: number | null = null;
	let lastLoadedVersion = $state<string | null>(null);
	let schemaRefreshTimer: number | null = null;

	const storageKey = $derived(analysisId ? `analysis-draft:${analysisId}` : null);

	// Timer: $derived can't schedule schema refresh.
	$effect(() => {
		if (!analysisId) return;
		if (schemaRefreshTimer) window.clearTimeout(schemaRefreshTimer);
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
		schemaRefreshTimer = window.setTimeout(() => {
			void datasourceStore.loadDatasources();
		}, 1500);
	});

	// Storage: $derived can't hydrate from IndexedDB.
	$effect(() => {
		if (!storageKey || draftLoaded) return;
		if (!analysisStore.tabs.length) return;
		const serverVersion = lastLoadedVersion ?? analysisStore.current?.version ?? null;
		if (!serverVersion) {
			draftLoaded = true;
			return;
		}

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
				version?: string | null;
				tabs: AnalysisTab[];
				activeTabId: string | null;
				resourceConfig: EngineResourceConfig | null;
				engineDefaults: EngineDefaults | null;
				selectedStepId: string | null;
				leftPaneCollapsed: boolean;
				rightPaneCollapsed: boolean;
				configPosition?: 'right' | 'bottom';
				bottomPaneHeight?: number;
			};
			if (parsed.analysisId !== analysisId) {
				draftLoaded = true;
				return;
			}
			if ((parsed.version ?? null) !== serverVersion) {
				void idbDelete(storageKey);
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
			if (parsed.configPosition) configPosition = parsed.configPosition;
			if (parsed.bottomPaneHeight) bottomPaneHeight = parsed.bottomPaneHeight;
			isDirty = true;
			draftLoaded = true;
		});
	});

	// Timer: $derived can't debounce draft persistence.
	$effect(() => {
		if (!storageKey || !draftLoaded) return;
		if (!analysisStore.tabs.length) return;
		if (!isEditingMode) return;
		const payload = {
			analysisId,
			version: analysisStore.current?.version ?? null,
			tabs: analysisStore.tabs,
			activeTabId: analysisStore.activeTabId,
			resourceConfig: analysisStore.resourceConfig,
			engineDefaults: analysisStore.engineDefaults,
			selectedStepId,
			leftPaneCollapsed,
			rightPaneCollapsed,
			configPosition,
			bottomPaneHeight
		};
		if (draftTimer) window.clearTimeout(draftTimer);
		draftTimer = window.setTimeout(() => {
			void idbSet(storageKey, JSON.stringify(payload));
		}, 400);
	});

	// Subscription: $derived can't sync store side effects.
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
	let configPosition = $state<'right' | 'bottom'>('right');
	let bottomPaneHeight = $state(300);
	let isResizingBottomPane = $state(false);
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
	// Subscription: $derived can't auto-collapse on media query.
	$effect(() => {
		if (isEditingMode && isNarrowScreen.current && !leftPaneCollapsed) {
			leftPaneCollapsed = true;
		}
	});

	// Auto-collapse right pane on very narrow screens
	// Subscription: $derived can't auto-collapse on media query.
	$effect(() => {
		if (isEditingMode && isMobileScreen.current && !rightPaneCollapsed) {
			rightPaneCollapsed = true;
		}
	});

	const analysisQuery = createQuery(() => ({
		queryKey: ['analysis', analysisId],
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			const result = await getAnalysisWithHeaders(analysisId);
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			analysisStore.applyAnalysis({
				...result.value.analysis,
				version: result.value.version
			});
			lastLoadedVersion = result.value.version;
			isDirty = false;
			return result.value.analysis;
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
			const result = await listDatasources(false);
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			// Sync to store in query success instead of effect
			datasourceStore.datasources = result.value;
			return result.value;
		}
	}));

	// Network: $derived can't fetch engine defaults.
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

	const datasourceId = $derived(analysisStore.activeTab?.datasource_id ?? undefined);
	const schemaKey = $derived.by(() => {
		const tab = analysisStore.activeTab;
		if (!tab || !analysisId) return undefined;
		if (tab.datasource_id) return tab.datasource_id;
		const config = (tab.datasource_config ?? {}) as Record<string, unknown>;
		const cfgAnalysisId = config.analysis_id as string | null | undefined;
		const cfgTabId = config.analysis_tab_id as string | null | undefined;
		if (!cfgAnalysisId || !cfgTabId) return undefined;
		if (String(cfgAnalysisId) !== String(analysisId)) return undefined;
		return `output:${analysisId}:${String(cfgTabId)}`;
	});
	const analysisTabName = $derived.by(() => {
		const tab = analysisStore.activeTab;
		if (!tab || !analysisId) return null;
		const config = (tab.datasource_config ?? {}) as Record<string, unknown>;
		const cfgAnalysisId = config.analysis_id as string | null | undefined;
		const cfgTabId = config.analysis_tab_id as string | null | undefined;
		if (!cfgAnalysisId || !cfgTabId) return null;
		if (String(cfgAnalysisId) !== String(analysisId)) return null;
		const sourceTab = analysisStore.tabs.find((item) => item.id === String(cfgTabId));
		return sourceTab?.name ?? null;
	});
	const previewDatasourceId = $derived.by(() => datasourceId ?? schemaKey ?? undefined);

	// Network: $derived can't load schema via network calls.
	$effect(() => {
		const datasourceIdValue = datasourceId;
		const schemaId = schemaKey;
		if (!schemaId) return;

		const existingSchema = analysisStore.sourceSchemas.get(schemaId);
		if (existingSchema) return;

		const current = datasourcesQuery.data?.find((ds) => ds.id === datasourceIdValue) ?? null;
		const activeTabConfig = (analysisStore.activeTab?.datasource_config ?? {}) as Record<
			string,
			unknown
		>;
		const analysisSourceId =
			(activeTabConfig.analysis_id as string | null) ??
			(current?.config?.analysis_id as string | null) ??
			null;
		const analysisTabId =
			(activeTabConfig.analysis_tab_id as string | null) ??
			(current?.config?.analysis_tab_id as string | null) ??
			null;
		const analysisPayload =
			analysisSourceId && analysisId && analysisSourceId === analysisId
				? buildAnalysisPipelinePayload(analysisId, analysisStore.tabs, datasourceStore.datasources)
				: null;

		if (analysisSourceId) {
			if (!analysisPayload) return;
			isLoadingSchema = true;
			const targetTabId = analysisTabId ?? analysisStore.activeTab?.id ?? null;
			getStepSchema({
				analysis_id: analysisSourceId,
				analysis_pipeline: analysisPayload,
				tab_id: targetTabId,
				target_step_id: 'source'
			}).match(
				(payload) => {
					const columns = payload.columns.map((name) => ({
						name,
						dtype: payload.column_types[name] ?? 'unknown',
						nullable: true
					}));
					analysisStore.setSourceSchema(schemaId, {
						columns,
						row_count: null
					});
					isLoadingSchema = false;
				},
				(error) => {
					track({
						event: 'schema_error',
						action: 'analysis_source_schema',
						target: analysisSourceId,
						meta: { message: error.message }
					});
					isLoadingSchema = false;
				}
			);
			return;
		}

		if (!datasourcesQuery.data || !datasourceIdValue) return;
		isLoadingSchema = true;
		getDatasourceSchema(datasourceIdValue).match(
			(schema) => {
				analysisStore.setSourceSchema(schemaId, schema);
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

	const currentDatasource = $derived.by(() => {
		if (!datasourceId) return null;
		const data = datasourcesQuery.data;
		if (!data) return null;
		return data.find((ds) => ds.id === datasourceId) ?? null;
	});
	const datasourceLabel = $derived(analysisTabName ?? currentDatasource?.name ?? null);

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
		const isChart = type === 'chart' || type.startsWith('plot_');
		if (type === 'view') {
			return { ...base, is_applied: true } as PipelineStep & { is_applied: boolean };
		}
		if (isChart) {
			return { ...base, is_applied: false } as PipelineStep & { is_applied: boolean };
		}
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
		rightPaneCollapsed = false;
		markUnsaved();
	}

	function handleInsertStep(type: string, target: DropTarget) {
		if (!isEditingMode) return;
		const step = buildStep(type);
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			selectedStepId = step.id;
			rightPaneCollapsed = false;
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
		rightPaneCollapsed = false;
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
				void datasourcesQuery.refetch();

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

	// Subscription: $derived can't manage lock teardown.
	$effect(() => {
		return () => {
			if (analysisId && hasLock(analysisId)) {
				void releaseLock(analysisId);
			}
			stopLockCheck();
		};
	});

	// Network: $derived can't check lock status on mount.
	$effect(() => {
		if (!analysisId) return;
		checkLockStatus(analysisId);
	});

	function toggleConfigPosition() {
		configPosition = configPosition === 'right' ? 'bottom' : 'right';
	}

	function handleBottomPaneResizeStart(e: PointerEvent) {
		e.preventDefault();
		isResizingBottomPane = true;
		const startY = e.clientY;
		const startHeight = bottomPaneHeight;

		function onMove(ev: PointerEvent) {
			const delta = startY - ev.clientY;
			bottomPaneHeight = Math.max(150, Math.min(startHeight + delta, window.innerHeight - 200));
		}

		function onUp() {
			isResizingBottomPane = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		}

		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

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
			output_datasource_id: makeId(),
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
			output_datasource_id: makeId(),
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
		analysisStore.updateTab(active.id, {
			datasource_id: datasourceId,
			datasource_config: null,
			name
		});
		if (schemaKey) analysisStore.sourceSchemas.delete(schemaKey);
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
			if (modalMode === 'change') {
				const active = analysisStore.activeTab;
				if (!active) return;
				analysisStore.updateTab(active.id, {
					datasource_id: analysisMatch?.id ?? null,
					datasource_config: { analysis_id: analysisId, analysis_tab_id: analysisTabId },
					name
				});
				if (schemaKey) analysisStore.sourceSchemas.delete(schemaKey);
				showDatasourceModal = false;
				markUnsaved();
				return;
			}
			if (analysisMatch) {
				handleAddAnalysisTab(
					analysisMatch.id,
					String(analysisMatch.config?.analysis_id ?? ''),
					name,
					analysisTabId
				);
				return;
			}
			const tab: AnalysisTab = {
				id: `tab-analysis-${Date.now()}`,
				output_datasource_id: makeId(),
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
		const config = (analysisStore.activeTab?.datasource_config ?? {}) as Record<string, unknown>;
		const sourceType = config.analysis_tab_id ? 'analysis' : 'datasource';
		modalSource = sourceType;
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
		<button class="btn-primary mt-4" onclick={() => goto(resolve('/analysis/new'))} type="button">
			Create analysis
		</button>
	</div>
{:else if analysisQuery.data}
	<div
		class="analysis-page flex h-full flex-col bg-secondary"
		class:resizing={isResizingBottomPane}
	>
		<header
			class="analysis-header flex items-stretch sticky top-0 h-11 bg-panel border-b border-tertiary"
		>
			<div
				class="header-left flex items-center h-full box-border border-r border-tertiary panel-width"
			>
				<div class="flex-1 flex flex-col min-w-0 overflow-hidden px-5">
					<h1
						contenteditable={isEditingMode}
						class="editable-title m-0 text-xs font-semibold uppercase whitespace-nowrap overflow-hidden text-ellipsis outline-none text-fg-primary tracking-[0.04em]"
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
							class="text-[0.625rem] whitespace-nowrap overflow-hidden text-ellipsis text-fg-faint tracking-[0.02em]"
							>{analysisQuery.data.description}</span
						>
					{/if}
				</div>
			</div>
			<div class="flex-1 min-w-0 overflow-hidden flex items-center justify-center gap-0">
				<button
					class="collapse-arrow collapse-arrow-left h-full flex items-center justify-center px-2 bg-panel border-none cursor-pointer shrink-0 text-fg-faint hover:text-fg-primary hover:bg-hover"
					class:collapsed={leftPaneCollapsed}
					onclick={() => (leftPaneCollapsed = !leftPaneCollapsed)}
					type="button"
					title={leftPaneCollapsed ? 'Expand operations' : 'Collapse operations'}
				>
					{#if leftPaneCollapsed}
						<ChevronRight size={12} />
					{:else}
						<ChevronLeft size={12} />
					{/if}
				</button>
				<div class="flex-1 overflow-hidden flex items-center">
					<div class="tabs flex items-center overflow-x-auto">
						{#each analysisStore.tabs.filter((t) => t.type === 'datasource') as tab (tab.id)}
							<div
								class="tab inline-flex items-center bg-transparent border-none text-xs font-medium uppercase text-fg-muted tracking-wide"
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
										class="tab-remove text-base leading-none ml-1 opacity-40 hover:opacity-100 hover:text-error"
										onclick={() => handleRemoveTab(tab.id)}
										type="button"
										aria-label="Remove tab"
									>
										<X size={10} />
									</button>
								{/if}
							</div>
						{/each}
						<div class="flex items-center">
							<button
								class="tab add-tab inline-flex items-center bg-transparent border-none cursor-pointer text-xs uppercase text-fg-faint hover:text-fg-primary"
								onclick={() => openDatasourceModal('add')}
								type="button"
								title="Add datasource tab"
							>
								<Plus size={12} />
							</button>
						</div>
					</div>
				</div>
			</div>
			<button
				class="config-position-toggle shrink-0 h-full flex items-center justify-center px-2 bg-panel border-none cursor-pointer text-fg-faint hover:text-fg-primary hover:bg-hover"
				onclick={toggleConfigPosition}
				type="button"
				title={configPosition === 'right' ? 'Move config to bottom' : 'Move config to side'}
			>
				{#if configPosition === 'right'}
					<PanelBottom size={13} />
				{:else}
					<PanelRight size={13} />
				{/if}
			</button>
			<button
				class="collapse-arrow collapse-arrow-right items-center px-2 bg-panel border-none text-fg-faint hover:text-fg-primary hover:bg-hover"
				class:collapsed={rightPaneCollapsed}
				onclick={() => (rightPaneCollapsed = !rightPaneCollapsed)}
				type="button"
				title={rightPaneCollapsed ? 'Expand configuration' : 'Collapse configuration'}
			>
				{#if configPosition === 'bottom'}
					{#if rightPaneCollapsed}
						<ChevronUp size={12} />
					{:else}
						<ChevronDown size={12} />
					{/if}
				{:else if rightPaneCollapsed}
					<ChevronLeft size={12} />
				{:else}
					<ChevronRight size={12} />
				{/if}
			</button>
			<div
				class="panel-width header-right flex items-center justify-end h-full box-border border-l border-tertiary"
			>
				<div class="mode-toggle-container relative items-center px-2">
					<button
						class="mode-toggle flex items-center cursor-pointer text-xs py-1.5 px-3 bg-tertiary border border-tertiary text-fg-secondary gap-2 hover:bg-hover hover:border-tertiary"
						onclick={() => (showModeDropdown = !showModeDropdown)}
						type="button"
					>
						{isEditingMode ? 'Editing' : 'Viewing'}
						<ChevronDown size={10} class="text-fg-faint" />
					</button>

					{#if showModeDropdown}
						<div
							class="mode-dropdown absolute left-0 min-w-35 bg-panel border border-tertiary p-1 z-100"
						>
							<button
								class="mode-option flex items-center bg-transparent border-none cursor-pointer text-xs text-left text-fg-secondary hover:bg-hover"
								onclick={() => setMode('viewing')}
								type="button"
							>
								{#if isEditingMode}
									<div class="w-3 h-3 border border-accent-primary"></div>
								{:else}
									<div class="w-3 h-3 bg-accent-primary"></div>
								{/if}
								<span>Viewing</span>
							</button>
							<button
								class="mode-option flex items-center bg-transparent border-none cursor-pointer text-xs text-left text-fg-secondary hover:bg-hover"
								onclick={() => setMode('editing')}
								type="button"
							>
								{#if isEditingMode}
									<div class="w-3 h-3 bg-accent-primary"></div>
								{:else}
									<div class="w-3 h-3 border border-accent-primary"></div>
								{/if}
								<span>Editing</span>
							</button>
							<button
								class="mode-option flex items-center bg-transparent border-none cursor-pointer text-xs text-left text-fg-secondary hover:bg-hover"
								onclick={openVersionModal}
								type="button"
							>
								<div class="w-3 h-3 border border-accent-primary"></div>
								<span>Rollback</span>
							</button>
						</div>
					{/if}
				</div>

				<div class="flex h-full flex-1 p-1 gap-1">
					<button
						class="cancel-button flex-1 h-full bg-tertiary border-none text-xs font-medium cursor-pointer text-fg-muted hover:bg-hover hover:text-fg-primary"
						onclick={discardChanges}
						disabled={!isEditingMode || !isDirty || isSaving || analysisStore.loading}
						type="button"
					>
						Cancel
					</button>
					<button
						class="save-button flex-1 h-full bg-transparent border-none text-xs font-medium cursor-pointer"
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

			<div class="flex flex-1 min-w-0 flex-col overflow-hidden">
				<div
					class="center-pane flex-1 min-w-50 min-h-0 flex bg-secondary"
					class:readonly={!isEditingMode}
					class:expanded={!isEditingMode}
				>
					<PipelineCanvas
						steps={analysisStore.pipeline}
						analysisId={analysisId ?? undefined}
						datasourceId={previewDatasourceId}
						datasource={currentDatasource}
						{datasourceLabel}
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

				{#if isEditingMode && configPosition === 'bottom'}
					<div
						class="bottom-pane shrink-0 overflow-hidden flex box-border bg-panel border-t border-tertiary"
						class:collapsed={rightPaneCollapsed}
						style="height: {rightPaneCollapsed ? 0 : bottomPaneHeight}px;"
					>
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="bottom-pane-resize-handle"
							onpointerdown={handleBottomPaneResizeStart}
						></div>
						<StepConfig
							step={selectedStepState}
							schema={analysisStore.calculatedSchema}
							{isLoadingSchema}
							onClose={handleCloseConfig}
							onConfigApply={markUnsaved}
						/>
					</div>
				{/if}
			</div>

			{#if isEditingMode && configPosition === 'right'}
				<div
					class="right-pane shrink-0 overflow-hidden flex h-full box-border bg-panel border-l border-tertiary panel-width"
					class:collapsed={rightPaneCollapsed}
				>
					<StepConfig
						step={selectedStepState}
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
	allowAnalysis
	{analysisTabs}
	excludeTabId={analysisStore.activeTabId}
	onSelect={handleDatasourceSelect}
	onClose={closeDatasourceModal}
/>

{#if showVersionModal}
	<div class="modal-backdrop" aria-hidden="true"></div>
	<div
		class="modal max-h-[80vh]"
		role="dialog"
		aria-modal="true"
		aria-labelledby="analysis-version-title"
	>
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
							<div class="flex min-w-0 flex-col">
								<div class="text-[0.65rem] uppercase tracking-widest text-fg-muted">
									Version {version.version} · {formatVersionDate(version.created_at)}
								</div>
								{#if editingVersionId === version.id}
									<input
										type="text"
										class="text-sm font-semibold text-fg-primary bg-transparent border border-tertiary px-1 py-0.5"
										bind:value={editingVersionName}
										onblur={() => commitRenameVersion(version.version)}
										onkeydown={(e) => {
											if (e.key === 'Enter') commitRenameVersion(version.version);
											if (e.key === 'Escape') editingVersionId = null;
										}}
									/>
								{:else}
									<div class="flex items-center.5">
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
