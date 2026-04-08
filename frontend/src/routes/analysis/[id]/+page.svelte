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
		buildOutputConfig,
		ensureTabDefaults,
		formatPipelineErrors,
		generateOutputName,
		isUuid,
		validatePipelineTabs
	} from '$lib/utils/analysis-tab';
	import {
		getAnalysisWithHeaders,
		listAnalysisVersions,
		restoreAnalysisVersion,
		renameAnalysisVersion,
		deleteAnalysisVersion
	} from '$lib/api/analysis';
	import { getDatasourceSchema, listDatasources } from '$lib/api/datasource';
	import { getStepSchema, spawnEngine } from '$lib/api/compute';
	import { acquireLock, releaseLock, watchLock, type LockWatcher } from '$lib/api/locks';
	import { authStore } from '$lib/stores/auth.svelte';
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import { getDefaultConfig } from '$lib/utils/step-config-defaults';
	import { isChartStep } from '$lib/components/pipeline/utils';
	import { idbGet, idbSet, idbDelete } from '$lib/utils/indexeddb';
	import { track } from '$lib/utils/audit-log';
	import { hashPipeline } from '$lib/utils/hash';
	import { applySteps } from '$lib/utils/pipeline';
	import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
	import type { DropTarget } from '$lib/stores/drag.svelte';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas, {
		type ClipboardStep
	} from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DragPreview from '$lib/components/pipeline/DragPreview.svelte';
	import DatasourceSelectorModal from '$lib/components/common/DatasourceSelectorModal.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { css, cx, spinner, button, input } from '$lib/styles/panda';
	import {
		ChevronDown,
		ChevronLeft,
		ChevronRight,
		ChevronUp,
		PanelRight,
		PanelBottom,
		Pencil,
		Plus,
		Trash2,
		X
	} from 'lucide-svelte';

	const analysisId = $derived($page.params.id ?? null);
	const validAnalysisId = $derived(analysisId && isUuid(analysisId) ? analysisId : null);
	let lastAnalysisId = $state<string | null>(null);

	let selectedStepId = $state<string | null>(null);
	const selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let saveError = $state('');
	let tabError = $state('');
	let tabErrorTimer = $state<number | null>(null);

	function flashTabError(msg: string) {
		tabError = msg;
		if (tabErrorTimer !== null) window.clearTimeout(tabErrorTimer);
		tabErrorTimer = window.setTimeout(() => {
			tabError = '';
			tabErrorTimer = null;
		}, 5000);
	}

	// Cleanup: $derived can't clear pending timers on destroy.
	$effect(() => {
		return () => {
			if (tabErrorTimer !== null) window.clearTimeout(tabErrorTimer);
		};
	});

	let draftLoaded = $state(false);
	let isDirty = $state(false);
	let draftTimer: number | null = null;
	let lastLoadedVersion = $state<string | null>(null);
	let hydratedGates = $state(new Set<string>());

	let lockMode = $state<'pending' | 'owned' | 'other'>('pending');
	let lockOwner = $state<string | null>(null);
	const userId = $derived(authStore.user?.id ?? null);
	let lockedByOther = $derived(
		lockMode === 'other' && lockOwner !== null && (userId === null || lockOwner !== userId)
	);
	const editorReadOnly = $derived(lockMode !== 'owned');

	function releaseCurrentLock(id: string, token: string): void {
		releaseLock('analysis', id, token).match(
			() => {},
			() => {}
		);
	}

	function startWatcher(id: string, token: string | null): LockWatcher {
		return watchLock({
			resourceType: 'analysis',
			resourceId: id,
			token,
			onStatus: (lock) => {
				lockOwner = lock?.owner_id ?? null;
			}
		});
	}

	// Websocket: $derived can't manage lock acquire + websocket watcher lifecycle.
	$effect(() => {
		const id = validAnalysisId;
		if (!id) return;

		lockMode = 'pending';
		lockOwner = null;

		let token: string | null = null;
		let watcher: LockWatcher | null = null;
		let alive = true;

		acquireLock('analysis', id).match(
			(status) => {
				if (!alive) {
					releaseCurrentLock(id, status.lock_token);
					return;
				}
				token = status.lock_token;
				lockMode = 'owned';
				lockOwner = status.owner_id;
				watcher = startWatcher(id, token);
			},
			(error) => {
				if (!alive) return;
				if (error.status === 409) {
					lockMode = 'other';
					watcher = startWatcher(id, null);
				}
			}
		);

		return () => {
			alive = false;
			watcher?.close();
			if (token) releaseCurrentLock(id, token);
			lockMode = 'pending';
			lockOwner = null;
		};
	});

	const storageKey = $derived(validAnalysisId ? `analysis-draft:${validAnalysisId}` : null);

	// Timer: $derived can't schedule schema refresh.
	$effect(() => {
		if (!analysisId) return;
		if (lastAnalysisId !== analysisId) {
			analysisStore.reset();
			schemaStore.reset();
			selectedStepId = null;
			hydratedGates = new Set();
			lastAnalysisId = analysisId;
		}
		draftLoaded = false;
	});

	// Storage: $derived can't hydrate from IndexedDB.
	$effect(() => {
		if (!storageKey || draftLoaded || editorReadOnly) return;
		if (!analysisStore.tabs.length) return;
		const serverVersion = lastLoadedVersion ?? analysisStore.current?.version ?? null;
		if (!serverVersion) {
			draftLoaded = true;
			return;
		}

		if (!analysisId) {
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
			const sanitized = parsed.tabs.map((tab, index) => ensureTabDefaults(tab, index));
			analysisStore.setTabs(sanitized);
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
		if (!storageKey || !draftLoaded || editorReadOnly) return;
		if (!analysisStore.tabs.length) return;
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
		return () => {
			if (draftTimer) window.clearTimeout(draftTimer);
		};
	});

	// Subscription: $derived can't sync store side effects.
	$effect(() => {
		if (!analysisId) return;
		isDirty = analysisStore.isDirty();
	});
	let isLoadingSchema = $state(false);
	let showDatasourceModal = $state(false);
	let modalMode = $state<'add' | 'change'>('add');
	let modalSource = $state<'datasource' | 'analysis'>('datasource');
	let leftPaneCollapsed = $state(false);
	let rightPaneCollapsed = $state(false);
	let configPosition = $state<'right' | 'bottom'>('right');
	let bottomPaneHeight = $state(300);
	let isResizingBottomPane = $state(false);
	let showVersionModal = $state(false);
	let versionError = $state<string | null>(null);
	let editingVersionId = $state<string | null>(null);
	let editingVersionName = $state('');

	// Responsive: auto-collapse panes on narrow screens
	const isNarrowScreen = new MediaQuery('max-width: 900px');
	const isMobileScreen = new MediaQuery('max-width: 600px');

	// Subscription: $derived can't auto-collapse on media query.
	$effect(() => {
		if (isNarrowScreen.current && !leftPaneCollapsed) {
			leftPaneCollapsed = true;
		}
	});

	// Subscription: $derived can't auto-collapse on media query.
	$effect(() => {
		if (isMobileScreen.current && !rightPaneCollapsed) {
			rightPaneCollapsed = true;
		}
	});

	const analysisQuery = createQuery(() => ({
		queryKey: ['analysis', analysisId],
		enabled: !!analysisId,
		staleTime: 0,
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			if (!validAnalysisId) throw new Error('Invalid analysis ID format');
			const result = await getAnalysisWithHeaders(validAnalysisId);
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
		retry: false
	}));

	let resetForRemoteLock = $state(false);

	// Locking: another owner means this view must snap back to persisted backend state.
	$effect(() => {
		if (!lockedByOther) {
			resetForRemoteLock = false;
			return;
		}
		if (resetForRemoteLock) return;
		resetForRemoteLock = true;

		showDatasourceModal = false;
		showVersionModal = false;
		versionError = null;
		editingVersionId = null;
		saveError = '';
		tabError = '';
		isDirty = false;
		analysisStore.setResourceConfig(null);

		if (storageKey) {
			void idbDelete(storageKey);
		}
		if (analysisQuery.data) {
			void analysisQuery.refetch();
		}
	});

	const versionsQuery = createQuery(() => ({
		queryKey: ['analysis-versions', analysisId],
		enabled: showVersionModal,
		staleTime: 0,
		queryFn: async () => {
			if (!analysisId) throw new Error('Analysis ID is required');
			if (!validAnalysisId) throw new Error('Invalid analysis ID format');
			const result = await listAnalysisVersions(validAnalysisId);
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
			datasourceStore.datasources = result.value;
			return result.value;
		}
	}));

	// Sync: $derived can't write to an external store.
	$effect(() => {
		if (datasourcesQuery.isSuccess || datasourcesQuery.isError) {
			datasourceStore.loaded = true;
		}
	});

	// Network: $derived can't fetch engine defaults.
	$effect(() => {
		if (!validAnalysisId || analysisStore.engineDefaults) return;
		spawnEngine(validAnalysisId).match(
			(status) => {
				if (status.defaults) {
					analysisStore.setEngineDefaults(status.defaults);
				}
			},
			(err) => {
				track({
					event: 'engine_error',
					action: 'spawn',
					target: validAnalysisId,
					meta: { message: err.message }
				});
			}
		);
	});

	// Network: $derived can't hydrate inferred schemas for expression/with_columns steps.
	$effect(() => {
		if (!validAnalysisId) return;
		const tab = analysisStore.activeTab;
		if (!tab) return;
		const pipeline = analysisStore.pipeline;
		if (!pipeline.length) return;
		const analysisPayload = buildAnalysisPipelinePayload(
			validAnalysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
		if (!analysisPayload) return;
		const pipelineHash = hashPipeline(applySteps(pipeline));
		const gate = `${validAnalysisId}:${tab.id}:${pipelineHash}`;
		if (hydratedGates.has(gate)) return;
		hydratedGates = new Set([...hydratedGates, gate]);

		const targets = pipeline.filter(
			(step) =>
				(step.type === 'expression' || step.type === 'with_columns') && step.is_applied !== false
		);
		for (const step of targets) {
			getStepSchema({
				analysis_id: validAnalysisId,
				analysis_pipeline: analysisPayload,
				tab_id: tab.id,
				target_step_id: step.id
			}).match(
				(res) => schemaStore.syncPreviewSchema(step.id, res, pipelineHash),
				(err) => {
					track({
						event: 'schema_error',
						action: 'hydrate',
						target: step.id,
						meta: { message: err.message }
					});
				}
			);
		}
	});

	const activeTab = $derived(analysisStore.activeTab);
	const datasourceId = $derived(activeTab?.datasource?.id ?? null);
	const schemaKey = $derived.by(() => {
		const tab = activeTab;
		if (!tab || !validAnalysisId) return undefined;
		const sourceTabId = tab.datasource.analysis_tab_id;
		if (sourceTabId) return `output:${validAnalysisId}:${String(sourceTabId)}`;
		if (tab.datasource.id) return tab.datasource.id;
		return undefined;
	});
	const analysisTabName = $derived.by(() => {
		const tab = activeTab;
		if (!tab || !validAnalysisId) return null;
		const sourceTabId = tab.datasource.analysis_tab_id;
		if (!sourceTabId) return null;
		const sourceTab = analysisStore.tabs.find((item) => item.id === String(sourceTabId));
		return sourceTab?.name ?? null;
	});
	const previewDatasourceId = $derived(datasourceId ?? schemaKey ?? null);

	// Network: $derived can't load schema via network calls.
	$effect(() => {
		const datasourceIdValue = datasourceId;
		const schemaId = schemaKey;
		if (!schemaId) return;

		const existingSchema = analysisStore.sourceSchemas.get(schemaId);
		if (existingSchema) return;

		const analysisTabId = activeTab?.datasource?.analysis_tab_id ?? null;
		const analysisPayload = validAnalysisId
			? buildAnalysisPipelinePayload(
					validAnalysisId,
					analysisStore.tabs,
					datasourceStore.datasources
				)
			: null;

		if (analysisTabId) {
			if (!analysisPayload) return;
			isLoadingSchema = true;
			const targetTabId = analysisTabId ?? activeTab?.id ?? null;
			getStepSchema({
				analysis_id: validAnalysisId ?? undefined,
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
						target: analysisId ?? '',
						meta: { message: error.message }
					});
					isLoadingSchema = false;
				}
			);
			return;
		}

		if (!datasourcesQuery.data || !datasourceIdValue) return;
		if (!isUuid(datasourceIdValue)) return;
		const ds = datasourcesQuery.data.find((d) => d.id === datasourceIdValue);
		if (ds?.source_type === 'analysis') return;
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

	function buildStep(type: string): PipelineStep {
		const base: PipelineStep = {
			id: crypto.randomUUID(),
			type,
			config: getDefaultConfig(type) as Record<string, unknown>,
			depends_on: []
		};
		const isChart = isChartStep(type);
		if (type === 'view') {
			return { ...base, is_applied: true } as PipelineStep;
		}
		if (isChart) {
			return { ...base, is_applied: false } as PipelineStep;
		}
		return { ...base, is_applied: false } as PipelineStep;
	}

	function markUnsaved() {
		if (editorReadOnly) return;
		isDirty = true;
	}

	function handleAddStep(type: string) {
		if (editorReadOnly) return;
		const step = buildStep(type);
		analysisStore.addStep(step);
		selectedStepId = step.id;
		rightPaneCollapsed = false;
		markUnsaved();
	}

	function handleInsertStep(type: string, target: DropTarget) {
		if (editorReadOnly) return;
		const step = buildStep(type);
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			selectedStepId = step.id;
			rightPaneCollapsed = false;
			markUnsaved();
		}
	}

	function handlePasteStep(payload: ClipboardStep, target: DropTarget) {
		if (editorReadOnly) return;
		const step: PipelineStep = {
			id: crypto.randomUUID(),
			type: payload.type,
			config: JSON.parse(JSON.stringify(payload.config)),
			depends_on: [],
			is_applied: payload.is_applied
		};
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			selectedStepId = step.id;
			rightPaneCollapsed = false;
			markUnsaved();
		}
	}

	function handleMoveStep(stepId: string, target: DropTarget) {
		if (editorReadOnly) return;
		analysisStore.moveStep(stepId, target.index, target.parentId, target.nextId);
		markUnsaved();
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
		rightPaneCollapsed = false;
	}

	function handleDeleteStep(stepId: string) {
		if (editorReadOnly) return;
		analysisStore.removeStep(stepId);
		if (selectedStepId === stepId) {
			selectedStepId = null;
		}
		markUnsaved();
	}

	function handleToggleStep(stepId: string) {
		if (editorReadOnly) return;
		const step = analysisStore.pipeline.find((item) => item.id === stepId);
		if (!step) return;
		const next = step.is_applied === false;
		analysisStore.updateStep(stepId, { is_applied: next } as Partial<PipelineStep>);
		markUnsaved();
	}

	async function handleSave() {
		if (isSaving || editorReadOnly) return;

		isSaving = true;
		saveError = '';

		const errors = validatePipelineTabs(analysisStore.tabs);
		if (errors.length) {
			saveError = `Failed to save pipeline: ${formatPipelineErrors(errors)}`;
			isSaving = false;
			return;
		}
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
				if (error.status === 409) {
					saveError = 'This analysis is locked by another user. Refresh to see the latest version.';
				} else if (error.status === 412) {
					saveError =
						'Analysis was modified elsewhere since you loaded it. Discard your changes and reload.';
				} else {
					saveError = `Failed to save pipeline: ${error.message}`;
				}
				isSaving = false;
			}
		);
	}

	async function discardChanges() {
		if (!analysisId) return;
		if (isSaving || editorReadOnly) return;
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
		if (editorReadOnly) return;
		const tabId = `tab-${datasourceId}-${Date.now()}`;
		const output = buildOutputConfig({
			outputId: crypto.randomUUID(),
			name: generateOutputName(),
			branch: 'master'
		});
		analysisStore.addTab({
			id: tabId,
			name,
			parent_id: null,
			datasource: {
				id: datasourceId,
				analysis_tab_id: null,
				config: { branch: 'master' }
			},
			output,
			steps: buildInitialSteps()
		});
		analysisStore.setActiveTab(tabId);
		showDatasourceModal = false;
		markUnsaved();
	}

	function handleAddAnalysisTab(
		datasourceId: string,
		sourceAnalysisId: string,
		name: string,
		sourceTabId: string | null
	) {
		if (editorReadOnly) return;
		if (
			modalMode === 'change' &&
			analysisId &&
			sourceAnalysisId === analysisId &&
			sourceTabId === analysisStore.activeTabId
		) {
			flashTabError('Select a different tab to avoid using the current tab as its own source.');
			return;
		}
		const tabId = `tab-analysis-${datasourceId}-${Date.now()}`;
		const output = buildOutputConfig({
			outputId: crypto.randomUUID(),
			name: generateOutputName(),
			branch: 'master'
		});
		analysisStore.addTab({
			id: tabId,
			name,
			parent_id: null,
			datasource: {
				id: datasourceId,
				analysis_tab_id: sourceTabId,
				config: { branch: 'master' }
			},
			output,
			steps: buildInitialSteps()
		});
		analysisStore.setActiveTab(tabId);
		if (analysisId && sourceTabId) {
			analysisStore.sourceSchemas.delete(`output:${analysisId}:${String(sourceTabId)}`);
		}
		showDatasourceModal = false;
		markUnsaved();
	}

	function handleChangeDatasource(datasourceId: string) {
		if (editorReadOnly) return;
		const active = activeTab;
		if (!active) return;
		analysisStore.updateTab(active.id, {
			datasource: { ...active.datasource, id: datasourceId, analysis_tab_id: null }
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
		if (editorReadOnly) return;
		if (source === 'analysis') {
			if (!analysisId) return;
			const analysisTabId = datasourceId;
			const sourceTab = analysisStore.tabs.find((item) => item.id === String(analysisTabId));
			const outputId =
				typeof sourceTab?.output.result_id === 'string' ? sourceTab.output.result_id : null;
			if (!outputId) {
				flashTabError('Selected analysis tab is missing an output datasource.');
				return;
			}
			if (modalMode === 'change') {
				const active = activeTab;
				if (!active) return;
				analysisStore.updateTab(active.id, {
					datasource: {
						...active.datasource,
						id: outputId,
						analysis_tab_id: analysisTabId
					}
				});
				if (schemaKey) analysisStore.sourceSchemas.delete(schemaKey);
				showDatasourceModal = false;
				markUnsaved();
				return;
			}
			handleAddAnalysisTab(outputId as string, analysisId, name, analysisTabId);
			return;
		}
		if (modalMode === 'change') {
			handleChangeDatasource(datasourceId);
			return;
		}
		handleAddTab(datasourceId, name);
	}

	function handleRemoveTab(tabId: string) {
		if (editorReadOnly) return;
		analysisStore.removeTab(tabId);
		markUnsaved();
	}

	function handleDuplicateTab(tabId: string) {
		if (editorReadOnly) return;
		const duplicated = analysisStore.duplicateTab(tabId);
		if (!duplicated) {
			flashTabError(
				'Failed to duplicate tab because the source pipeline dependencies are invalid.'
			);
			return;
		}
		markUnsaved();
	}

	function handleDuplicateActiveTab() {
		const currentTabId = analysisStore.activeTab?.id;
		if (!currentTabId) return;
		handleDuplicateTab(currentTabId);
	}

	function handleRenameSourceTab(nextName: string) {
		if (editorReadOnly) return;
		const active = activeTab;
		if (!active) return;
		const trimmed = nextName.trim();
		if (!trimmed || trimmed === active.name) return;
		analysisStore.updateTab(active.id, { name: trimmed });
		markUnsaved();
	}

	function openDatasourceModal(mode: 'add' | 'change' = 'add') {
		if (editorReadOnly) return;
		modalMode = mode;
		const sourceType = activeTab?.datasource.analysis_tab_id ? 'analysis' : 'datasource';
		modalSource = sourceType;
		showDatasourceModal = true;
	}

	function closeDatasourceModal() {
		showDatasourceModal = false;
		tabError = '';
	}

	function openVersionModal() {
		versionError = null;
		showVersionModal = true;
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
		if (!analysisId || editorReadOnly) return;
		versionError = null;
		const result = await restoreAnalysisVersion(analysisId, version);
		if (result.isErr()) {
			versionError = result.error.message;
			return;
		}
		schemaStore.reset();
		analysisStore.previewRuns.clear();
		analysisStore.applyAnalysis(result.value);
		lastLoadedVersion = result.value.version ?? lastLoadedVersion;
		selectedStepId = null;
		showVersionModal = false;
		isDirty = false;
	}

	function startRenameVersion(id: string, name: string) {
		if (editorReadOnly) return;
		editingVersionId = id;
		editingVersionName = name;
	}

	async function commitRenameVersion(version: number) {
		if (!analysisId || !editingVersionId || editorReadOnly) return;
		const trimmed = editingVersionName.trim();
		if (!trimmed) {
			editingVersionId = null;
			return;
		}
		const result = await renameAnalysisVersion(analysisId, version, trimmed);
		if (result.isErr()) {
			versionError = result.error.message;
			editingVersionId = null;
			return;
		}
		versionsQuery.refetch();
		editingVersionId = null;
	}

	async function handleDeleteVersion(version: number) {
		if (!analysisId || editorReadOnly) return;
		versionError = null;
		const result = await deleteAnalysisVersion(analysisId, version);
		if (result.isErr()) {
			versionError = result.error.message;
			return;
		}
		versionsQuery.refetch();
	}
</script>

{#if analysisQuery.isLoading}
	<div
		class={css({ display: 'flex', alignItems: 'center', height: '100%', justifyContent: 'center' })}
	>
		<div class={spinner()}></div>
	</div>
{:else if analysisQuery.isError}
	<div
		data-testid="analysis-load-error"
		class={css({
			display: 'flex',
			alignItems: 'center',
			paddingX: '2.5',
			paddingY: '3',
			border: 'none',
			borderLeftWidth: '2',

			fontSize: 'xs',
			lineHeight: '1.5',
			backgroundColor: 'transparent',
			borderLeftColor: 'border.error',
			color: 'fg.error',
			height: '100%',
			flexDirection: 'column',
			justifyContent: 'center',
			textAlign: 'center',
			gap: '4'
		})}
	>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				fontSize: 'xl',
				fontWeight: 'bold',
				width: 'logoLg',
				height: 'logoLg',
				borderWidth: '1'
			})}
		>
			!
		</div>
		<h2 class={css({ margin: '0' })}>Error loading analysis</h2>
		<p class={css({ margin: '0' })}>
			{analysisQuery.error instanceof Error ? analysisQuery.error.message : 'Unknown error'}
		</p>
		<button
			class={cx(button({ variant: 'primary' }), css({ marginTop: '4' }))}
			onclick={() => goto(resolve('/analysis/new'))}
			type="button"
		>
			Create analysis
		</button>
	</div>
{:else if analysisQuery.data}
	<div
		class={css({
			display: 'flex',
			height: '100%',
			flexDirection: 'column',
			backgroundColor: 'bg.secondary',
			...(isResizingBottomPane ? { userSelect: 'none', cursor: 'ns-resize' } : {})
		})}
	>
		<header
			class={css({
				display: 'flex',
				alignItems: 'stretch',
				position: 'sticky',
				top: '0',
				height: 'headerSm',
				backgroundColor: 'bg.primary',
				zIndex: 'header'
			})}
		>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					height: '100%',
					boxSizing: 'border-box',
					borderRightWidth: '1',
					width: 'operationsPanel',
					transitionProperty: 'width, visibility',
					transitionDuration: 'normal'
				})}
			>
				<div
					class={css({
						flex: '1',
						display: 'flex',
						flexDirection: 'column',
						minWidth: '0',
						overflow: 'hidden',
						paddingX: '5'
					})}
				>
					<h1
						contenteditable={!editorReadOnly}
						class={css({
							margin: '0',
							fontSize: 'xs',
							fontWeight: 'semibold',
							textTransform: 'uppercase',
							whiteSpace: 'nowrap',
							overflow: 'hidden',
							textOverflow: 'ellipsis',
							outline: 'none',
							letterSpacing: 'wide2',
							cursor: editorReadOnly ? 'default' : 'text',
							_focus: {
								backgroundColor: 'bg.hover',

								paddingX: '1',
								marginX: 'calc({spacing.1} * -1)'
							}
						})}
						onblur={(e) => {
							if (editorReadOnly) {
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
							class={css({
								fontSize: '2xs',
								whiteSpace: 'nowrap',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								color: 'fg.faint',
								letterSpacing: 'tight2'
							})}>{analysisQuery.data.description}</span
						>
					{/if}
				</div>
			</div>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					flex: '1',
					minWidth: '0',
					overflow: 'hidden',
					justifyContent: 'center',
					gap: '0'
				})}
			>
				<button
					class={css({
						height: '100%',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						paddingX: '2',
						backgroundColor: 'bg.primary',
						border: 'none',
						cursor: 'pointer',
						flexShrink: '0',
						color: 'fg.faint',
						_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
					})}
					onclick={() => {
						leftPaneCollapsed = !leftPaneCollapsed;
						rightPaneCollapsed = !rightPaneCollapsed;
					}}
					type="button"
					title={leftPaneCollapsed ? 'Expand panels' : 'Collapse panels'}
				>
					{#if leftPaneCollapsed}
						<ChevronRight size={12} />
					{:else}
						<ChevronLeft size={12} />
					{/if}
				</button>
				<div class={css({ display: 'flex', alignItems: 'center', flex: '1', overflow: 'hidden' })}>
					<div class={css({ display: 'flex', alignItems: 'center', overflowX: 'auto', gap: '0' })}>
						{#each analysisStore.tabs as tab (tab.id)}
							<div
								class={css({
									display: 'inline-flex',
									alignItems: 'center',
									backgroundColor: 'transparent',
									border: 'none',
									fontSize: 'xs',
									fontWeight: 'medium',
									textTransform: 'uppercase',
									color: 'fg.muted',
									letterSpacing: 'wide',
									...(analysisStore.activeTab?.id === tab.id
										? { color: 'fg.primary', backgroundColor: 'bg.secondary' }
										: {})
								})}
							>
								<button
									class={css({
										display: 'inline-flex',
										alignItems: 'center',
										minWidth: '0',
										backgroundColor: 'transparent',
										border: 'none',
										cursor: 'pointer'
									})}
									onclick={() => handleSelectTab(tab.id)}
									type="button"
									data-testid={`tab-button-${tab.id}`}
									data-tab-name={tab.name}
								>
									<span
										class={css({
											whiteSpace: 'nowrap',
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											maxWidth: 'inputSm'
										})}
									>
										{tab.name}
									</span>
								</button>
								{#if analysisStore.tabs.length > 1}
									<button
										class={css({
											fontSize: 'md',
											lineHeight: '1',
											marginLeft: '1',
											backgroundColor: 'transparent',
											opacity: '0.4',
											_hover: { opacity: '1', color: 'fg.error' }
										})}
										onclick={() => handleRemoveTab(tab.id)}
										type="button"
										aria-label="Remove tab"
										disabled={editorReadOnly}
									>
										<X size={10} />
									</button>
								{/if}
							</div>
						{/each}
						<div class={css({ display: 'flex', alignItems: 'center' })}>
							<button
								class={css({
									display: 'inline-flex',
									alignItems: 'center',
									backgroundColor: 'transparent',
									border: 'none',
									cursor: 'pointer',
									fontSize: 'xs',
									textTransform: 'uppercase',
									color: 'fg.faint',
									_hover: { color: 'fg.primary' }
								})}
								onclick={() => openDatasourceModal('add')}
								type="button"
								title="Add datasource tab"
								disabled={editorReadOnly}
							>
								<Plus size={12} />
							</button>
						</div>
					</div>
				</div>
			</div>
			<button
				class={css({
					flexShrink: '0',
					height: '100%',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					paddingX: '2',
					backgroundColor: 'bg.primary',
					border: 'none',
					cursor: 'pointer',
					color: 'fg.faint',
					_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
				})}
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
				class={css({
					display: 'flex',
					alignItems: 'center',
					paddingX: '2',
					backgroundColor: 'bg.primary',
					border: 'none',
					color: 'fg.faint',
					_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
				})}
				onclick={() => {
					rightPaneCollapsed = !rightPaneCollapsed;
					leftPaneCollapsed = !leftPaneCollapsed;
				}}
				type="button"
				title={rightPaneCollapsed ? 'Expand panels' : 'Collapse panels'}
			>
				{#if configPosition === 'bottom'}
					{#if leftPaneCollapsed}
						<ChevronUp size={12} />
					{:else}
						<ChevronDown size={12} />
					{/if}
				{:else if leftPaneCollapsed}
					<ChevronLeft size={12} />
				{:else}
					<ChevronRight size={12} />
				{/if}
			</button>
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'flex-end',
					height: '100%',
					boxSizing: 'border-box',
					borderLeftWidth: '1',
					width: 'operationsPanel',
					transitionProperty: 'width, visibility',
					transitionDuration: 'normal'
				})}
			>
				<div class={css({ display: 'flex', height: '100%', flex: '1', padding: '1', gap: '1' })}>
					<button
						class={css({
							flex: '1',
							height: '100%',
							backgroundColor: 'bg.tertiary',
							border: 'none',
							fontSize: 'xs',
							fontWeight: 'medium',
							cursor: 'pointer',
							color: 'fg.muted',
							_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
							_disabled: { opacity: '0.5', cursor: 'not-allowed' }
						})}
						onclick={discardChanges}
						disabled={!isDirty || isSaving || analysisStore.loading || editorReadOnly}
						type="button"
					>
						Discard
					</button>
					<div
						class={css({
							display: 'flex',
							flex: '1',
							borderRadius: 'xs',
							overflow: 'hidden',
							...(isDirty ? { backgroundColor: 'bg.warning' } : { backgroundColor: 'bg.tertiary' })
						})}
					>
						<button
							class={css({
								flex: '1',
								height: '100%',
								border: 'none',
								backgroundColor: 'transparent',
								fontSize: 'xs',
								fontWeight: 'medium',
								cursor: 'pointer',
								_disabled: { opacity: '0.5', cursor: 'not-allowed' },
								...(isDirty ? { color: 'fg.warning' } : { color: 'fg.success' })
							})}
							onclick={handleSave}
							disabled={isSaving || analysisStore.loading || editorReadOnly}
							type="button"
							data-save-state={editorReadOnly
								? 'locked'
								: isSaving
									? 'saving'
									: isDirty
										? 'dirty'
										: 'clean'}
						>
							{editorReadOnly ? 'Locked' : isSaving ? 'Saving...' : isDirty ? 'Save' : 'Saved'}
						</button>
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								height: '100%',
								backgroundColor: 'transparent',
								border: 'none',
								borderLeftWidth: '1',
								borderLeftColor: isDirty ? 'border.warning' : 'border.primary',
								cursor: 'pointer',
								paddingX: '1.5',
								color: isDirty ? 'fg.warning' : 'fg.faint',
								opacity: '0.6',
								_hover: { opacity: '1' }
							})}
							onclick={openVersionModal}
							type="button"
							title="Rollback to previous version"
							data-testid="version-history-trigger"
						>
							<ChevronDown size={12} />
						</button>
					</div>
				</div>
			</div>
		</header>

		{#if saveError}
			<div class={css({ paddingX: '4', paddingY: '2' })} data-testid="save-error">
				<Callout tone="error">{saveError}</Callout>
			</div>
		{/if}

		{#if lockedByOther}
			<div class={css({ paddingX: '4', paddingY: '2' })} data-testid="lock-banner">
				<Callout tone="warn"
					>This analysis is being edited by another user. Saving is disabled until the lock is
					released.</Callout
				>
			</div>
		{/if}

		<div
			class={css({
				display: 'flex',
				flex: '1',
				overflow: 'hidden',
				userSelect: 'none',
				backgroundColor: 'bg.secondary'
			})}
			role="application"
		>
			<div
				class={css({
					flexShrink: '0',
					overflow: 'hidden',
					display: 'flex',
					height: '100%',
					boxSizing: 'border-box',
					backgroundColor: 'bg.primary',
					borderRightWidth: '1',
					width: 'operationsPanel',
					transitionProperty: 'width, visibility',
					transitionDuration: 'normal',
					'& > *': { width: '100%', visibility: 'visible' },
					...(leftPaneCollapsed
						? { width: '0', border: 'none', '& > *': { width: '100%', visibility: 'hidden' } }
						: {})
				})}
			>
				<StepLibrary
					onAddStep={handleAddStep}
					onInsertStep={handleInsertStep}
					readOnly={editorReadOnly}
				/>
			</div>

			<div
				class={css({
					display: 'flex',
					flex: '1',
					minWidth: '0',
					flexDirection: 'column',
					overflow: 'hidden'
				})}
			>
				<div
					class={css({
						flex: '1',
						minWidth: 'listSm',
						minHeight: '0',
						display: 'flex',
						backgroundColor: 'bg.secondary',
						'& > *': { width: '100%' }
					})}
				>
					<PipelineCanvas
						steps={analysisStore.pipeline}
						analysisId={analysisId || undefined}
						datasourceId={previewDatasourceId || undefined}
						datasource={currentDatasource}
						{datasourceLabel}
						tabName={analysisStore.activeTab?.name}
						activeTab={analysisStore.activeTab}
						onStepClick={handleSelectStep}
						onStepDelete={handleDeleteStep}
						onStepToggle={handleToggleStep}
						onInsertStep={handleInsertStep}
						onPasteStep={handlePasteStep}
						onMoveStep={handleMoveStep}
						onChangeDatasource={() => openDatasourceModal('change')}
						onRenameTab={handleRenameSourceTab}
						onDuplicateTab={handleDuplicateActiveTab}
						readOnly={editorReadOnly}
					/>
				</div>

				{#if configPosition === 'bottom'}
					<div
						class={css({
							flexShrink: '0',
							overflow: 'hidden',
							display: 'flex',
							boxSizing: 'border-box',
							backgroundColor: 'bg.primary',
							borderTopWidth: '1',
							width: '100%',
							position: 'relative',
							transitionProperty: 'height, visibility',
							transitionDuration: 'normal',
							'& > .step-config': { width: '100%', flex: '1', minHeight: '0' },
							...(rightPaneCollapsed ? { border: 'none' } : {})
						})}
						style:height="{rightPaneCollapsed ? 0 : bottomPaneHeight}px"
					>
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class={css({
								position: 'absolute',
								top: '-3px',
								left: '0',
								right: '0',
								height: 'barTall',
								cursor: 'ns-resize',
								zIndex: '5',
								_hover: { background: 'accent.primary', opacity: '0.4' },
								_active: { background: 'accent.primary', opacity: '0.4' }
							})}
							onpointerdown={handleBottomPaneResizeStart}
						></div>
						<StepConfig
							step={selectedStepState}
							schema={analysisStore.calculatedSchema}
							{isLoadingSchema}
							onClose={handleCloseConfig}
							onConfigApply={markUnsaved}
							readOnly={editorReadOnly}
						/>
					</div>
				{/if}
			</div>

			{#if configPosition === 'right'}
				<div
					class={css({
						flexShrink: '0',
						overflow: 'hidden',
						display: 'flex',
						height: '100%',
						boxSizing: 'border-box',
						backgroundColor: 'bg.primary',
						borderLeftWidth: '1',
						width: 'operationsPanel',
						transitionProperty: 'width, visibility',
						transitionDuration: 'normal',
						'& > *': { width: '100%', visibility: 'visible' },
						...(rightPaneCollapsed
							? { width: '0', border: 'none', '& > *': { width: '100%', visibility: 'hidden' } }
							: {})
					})}
				>
					<StepConfig
						step={selectedStepState}
						schema={analysisStore.calculatedSchema}
						{isLoadingSchema}
						onClose={handleCloseConfig}
						onConfigApply={markUnsaved}
						readOnly={editorReadOnly}
					/>
				</div>
			{/if}
		</div>
	</div>
{/if}

<svelte:window
	onkeydown={handleVersionKeydown}
	onbeforeunload={(e) => {
		if (!isDirty) return;
		e.preventDefault();
	}}
/>

{#if tabError}
	<div
		class={css({
			position: 'fixed',
			bottom: '4',
			left: '50%',
			transform: 'translateX(-50%)',
			zIndex: '1002',
			width: 'min(480px, 90vw)'
		})}
	>
		<Callout tone="error">{tabError}</Callout>
	</div>
{/if}

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
	<div
		class={css({ position: 'fixed', inset: '0', background: 'bg.overlay', zIndex: 'modal' })}
		aria-hidden="true"
	></div>
	<div
		class={css({
			position: 'fixed',
			left: '50%',
			top: '50%',
			transform: 'translate(-50%, -50%)',
			width: 'min(720px, 92vw)',
			maxHeight: '80vh',
			backgroundColor: 'bg.primary',
			borderWidth: '1',
			zIndex: '1001',
			display: 'flex',
			flexDirection: 'column',
			_focus: { outline: 'none' }
		})}
		role="dialog"
		aria-modal="true"
		aria-labelledby="analysis-version-title"
	>
		<div
			class={css({
				display: 'flex',
				justifyContent: 'space-between',
				alignItems: 'center',
				paddingX: '4',
				paddingY: '3',
				borderBottomWidth: '1',
				'& h2': { margin: '0', fontSize: 'md', color: 'fg.primary' }
			})}
		>
			<h2 id="analysis-version-title">Version history</h2>
			<button
				class={css({
					background: 'transparent',
					border: 'none',
					color: 'fg.muted',
					cursor: 'pointer',
					fontSize: 'xl',
					padding: '1',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					transitionProperty: 'color, background-color',
					transitionDuration: 'normal',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={closeVersionModal}
				aria-label="Close version history"
			>
				<X size={16} />
			</button>
		</div>
		<div
			class={css({
				padding: '4',
				overflowY: 'auto',
				display: 'flex',
				flexDirection: 'column',
				gap: '3'
			})}
		>
			{#if versionError}
				<div
					data-testid="version-error"
					class={css({
						paddingX: '2.5',
						paddingY: '3',
						border: 'none',
						borderLeftWidth: '2',

						marginTop: '3',
						marginBottom: '0',
						fontSize: 'xs',
						lineHeight: '1.5',
						backgroundColor: 'transparent',
						borderLeftColor: 'border.error',
						color: 'fg.error',
						margin: '0'
					})}
				>
					{versionError}
				</div>
			{/if}
			{#if versionsQuery.isLoading}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						padding: '8',
						fontSize: 'sm',
						color: 'fg.muted'
					})}
				>
					Loading...
				</div>
			{:else if versionsQuery.isError}
				<div
					data-testid="version-load-error"
					class={css({
						paddingX: '2.5',
						paddingY: '3',
						border: 'none',
						borderLeftWidth: '2',

						marginTop: '3',
						marginBottom: '0',
						fontSize: 'xs',
						lineHeight: '1.5',
						backgroundColor: 'transparent',
						borderLeftColor: 'border.error',
						color: 'fg.error',
						margin: '0'
					})}
				>
					Failed to load version history.
				</div>
			{:else if !versionsQuery.data?.length}
				<p
					class={css({
						color: 'fg.muted',
						fontStyle: 'italic',
						textAlign: 'center',
						padding: '4',
						margin: '0'
					})}
				>
					No versions available.
				</p>
			{:else}
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					{#each versionsQuery.data as version (version.id)}
						<div
							data-testid="version-row-{version.version}"
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between',
								gap: '4',
								borderWidth: '1',
								backgroundColor: 'bg.tertiary',
								padding: '3'
							})}
						>
							<div class={css({ display: 'flex', minWidth: '0', flexDirection: 'column' })}>
								<div
									class={css({
										fontSize: '2xs2',
										textTransform: 'uppercase',
										letterSpacing: 'widest',
										color: 'fg.muted'
									})}
								>
									Version {version.version} · {formatVersionDate(version.created_at)}
								</div>
								{#if editingVersionId === version.id}
									<input
										type="text"
										class={cx(
											input(),
											css({
												fontSize: 'sm',
												fontWeight: 'semibold',
												backgroundColor: 'transparent',
												paddingX: '1',
												paddingY: '0.5'
											})
										)}
										id="version-name-{version.id}"
										aria-label="Version name"
										bind:value={editingVersionName}
										disabled={editorReadOnly}
										onblur={() => commitRenameVersion(version.version)}
										onkeydown={(e) => {
											if (e.key === 'Enter') commitRenameVersion(version.version);
											else if (e.key === 'Escape') editingVersionId = null;
										}}
									/>
								{:else}
									<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
										<span class={css({ fontSize: 'sm', fontWeight: 'semibold' })}>
											{version.name}
										</span>
										<button
											class={css({
												padding: '0.5',
												backgroundColor: 'transparent',
												borderColor: 'transparent',
												color: 'fg.muted',
												_hover: { color: 'fg.primary' }
											})}
											title="Rename version"
											data-testid="version-rename-{version.version}"
											onclick={() => startRenameVersion(version.id, version.name)}
											disabled={editorReadOnly}
										>
											<Pencil size={12} />
										</button>
									</div>
								{/if}
								{#if version.description}
									<div class={css({ fontSize: 'xs', color: 'fg.muted' })}>
										{version.description}
									</div>
								{/if}
							</div>
							<div
								class={css({ display: 'flex', gap: '1', flexShrink: '0', alignItems: 'center' })}
							>
								<button
									class={css({
										padding: '0.5',
										backgroundColor: 'transparent',
										border: 'none',
										color: 'fg.muted',
										cursor: 'pointer',
										_hover: { color: 'fg.error' }
									})}
									title="Delete version"
									data-testid="version-delete-{version.version}"
									onclick={() => handleDeleteVersion(version.version)}
									disabled={editorReadOnly}
								>
									<Trash2 size={14} />
								</button>
								<button
									class={cx(button({ variant: 'secondary', size: 'sm' }))}
									data-testid="version-restore-{version.version}"
									onclick={() => handleRestoreVersion(version.version)}
									type="button"
									disabled={editorReadOnly}
								>
									Restore
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
		<div
			class={css({
				paddingX: '4',
				paddingY: '3',
				borderTopWidth: '1',
				display: 'flex',
				justifyContent: 'flex-end',
				gap: '2'
			})}
		>
			<button class={button({ variant: 'secondary' })} onclick={closeVersionModal} type="button"
				>Close</button
			>
		</div>
	</div>
{/if}

<DragPreview />
