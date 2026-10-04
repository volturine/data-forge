<script lang="ts">
	import { page } from '$app/stores';
	import { afterNavigate } from '$app/navigation';
	import { onDestroy, onMount } from 'svelte';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { BuildStreamStore } from '$lib/stores/build-stream.svelte';
	import { formatPipelineErrors, isUuid, validatePipelineTabs } from '$lib/utils/analysis-tab';
	import { favoriteAnalysis, unfavoriteAnalysis, type AnalysisDetail } from '$lib/api/analysis';
	import { analysisQueryKey, fetchAnalysis } from '$lib/queries/analysis';
	import { listDatasources } from '$lib/api/datasource';
	import type { Analysis } from '$lib/types/analysis';
	import { idbDelete } from '$lib/utils/indexeddb';
	import StepLibrary from '$lib/components/pipeline/StepLibrary.svelte';
	import PipelineCanvas from '$lib/components/pipeline/PipelineCanvas.svelte';
	import StepConfig from '$lib/components/pipeline/StepConfig.svelte';
	import DragPreview from '$lib/components/pipeline/DragPreview.svelte';
	import DatasourceSelectorModal from '$lib/components/common/DatasourceSelectorModal.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { schemaStore } from '$lib/stores/schema.svelte';
	import { favoriteStore } from '$lib/stores/favorites.svelte';
	import { css } from '$lib/styles/panda';
	import AnalysisEditorLoadGate from '$lib/components/analysis-editor/AnalysisEditorLoadGate.svelte';
	import AnalysisEditorHeader from '$lib/components/analysis-editor/AnalysisEditorHeader.svelte';
	import AnalysisEditorDescriptionModal from '$lib/components/analysis-editor/AnalysisEditorDescriptionModal.svelte';
	import AnalysisEditorExportModal from '$lib/components/analysis-editor/AnalysisEditorExportModal.svelte';
	import AnalysisEditorVersionModal from '$lib/components/analysis-editor/AnalysisEditorVersionModal.svelte';
	import {
		setupInferredSchemaHydrationEffect,
		setupSourceSchemaLoadingEffect
	} from '$lib/components/analysis-editor/analysis-editor-schema-effects.svelte';
	import { createEditorLockController } from '$lib/components/analysis-editor/analysis-editor-lock.svelte';
	import { createAnalysisEditorActions } from '$lib/components/analysis-editor/analysis-editor-actions.svelte';
	import { createDraftController } from '$lib/components/analysis-editor/analysis-editor-draft.svelte';
	import { useNamespace } from '$lib/stores/namespace.svelte';

	const queryClient = useQueryClient();
	const ns = useNamespace();
	const analysisId = $derived($page.params.id ?? null);
	const validAnalysisId = $derived(analysisId && isUuid(analysisId) ? analysisId : null);

	let selectedStepId = $state<string | null>(null);
	const buildStore = new BuildStreamStore();
	const selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let saveError = $state('');

	const isDirty = $derived(analysisStore.isDirty());
	let lastLoadedVersion = $state<string | null>(null);

	const lock = createEditorLockController({
		validAnalysisId: () => validAnalysisId,
		getDraftLoaded: () => draft.draftLoaded,
		getIsSaving: () => isSaving,
		getIsDirty: () => isDirty,
		onOwned: () => draft.hydrate(),
		onLockedByOther: () => snapBackFromRemoteLock()
	});
	const editorAccessState = $derived(lock.editorAccessState);
	const lockReadOnly = $derived(lock.lockReadOnly);
	const editorReadOnly = $derived(lock.editorReadOnly);

	function persistDraft(): void {
		if (editorReadOnly) return;
		draft.schedulePersist();
	}

	function markUnsaved() {
		persistDraft();
		hydrateInferredSchemas();
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
		rightPaneCollapsed = false;
		draft.schedulePersist();
	}

	const actions = createAnalysisEditorActions({
		analysisId: () => analysisId,
		editorReadOnly: () => editorReadOnly,
		activeTab: () => analysisStore.activeTab,
		schemaKey: () => schemaKey,
		markUnsaved,
		selectStep: (stepId) => {
			selectedStepId = stepId;
		},
		clearSelectedStep: (stepId) => {
			if (selectedStepId === stepId) {
				selectedStepId = null;
			}
		},
		expandRightPane: () => {
			rightPaneCollapsed = false;
		}
	});

	onDestroy(() => {
		synchronizedEditorRoute = null;
		actions.clearTabErrorTimer();
		buildStore.close();
		lock.stop();
		cancelEditorServices();
		draft.flush();
	});

	const storageKey = $derived(validAnalysisId ? `analysis-draft:${validAnalysisId}` : null);

	function resetForAnalysisId(id: string | null): void {
		if (!id) return;
		if (analysisStore.current?.id === id) return;
		analysisStore.reset();
		schemaStore.reset();
		selectedStepId = null;
		draft.reset();
	}

	const draft = createDraftController({
		getStorageKey: () => storageKey,
		getAnalysisId: () => analysisId,
		blockedFromHydration: () =>
			lockReadOnly || lock.remoteLockSyncPending || lock.remoteLockSyncFailed,
		readOnly: () => editorReadOnly,
		hasTabs: () => analysisStore.tabs.length > 0,
		getServerVersion: () => lastLoadedVersion ?? analysisStore.currentRevision,
		buildPayload: () => ({
			analysisId,
			version: analysisStore.currentRevision,
			tabs: analysisStore.tabs,
			activeTabId: analysisStore.activeTabId,
			resourceConfig: analysisStore.resourceConfig,
			selectedStepId,
			leftPaneCollapsed,
			rightPaneCollapsed,
			configPosition,
			bottomPaneHeight
		}),
		applyDraft: (parsed) => {
			analysisStore.setTabs(parsed.tabs);
			analysisStore.activeTabId = parsed.activeTabId;
			analysisStore.setResourceConfig(parsed.resourceConfig);
			selectedStepId = parsed.selectedStepId;
			leftPaneCollapsed = parsed.leftPaneCollapsed;
			rightPaneCollapsed = parsed.rightPaneCollapsed;
			if (parsed.configPosition) configPosition = parsed.configPosition;
			if (parsed.bottomPaneHeight) bottomPaneHeight = parsed.bottomPaneHeight;
		}
	});

	let leftPaneCollapsed = $state(false);
	let rightPaneCollapsed = $state(false);
	let configPosition = $state<'right' | 'bottom'>('right');
	let bottomPaneHeight = $state(300);

	function setLeftPaneCollapsed(next: boolean): void {
		leftPaneCollapsed = next;
		persistDraft();
	}

	function setRightPaneCollapsed(next: boolean): void {
		rightPaneCollapsed = next;
		persistDraft();
	}

	function setConfigPosition(next: 'right' | 'bottom'): void {
		configPosition = next;
		persistDraft();
	}
	let isResizingBottomPane = $state(false);
	let showVersionModal = $state(false);
	let showDescriptionModal = $state(false);
	let showExportModal = $state(false);
	let exportScopeTabId = $state<string | null>(null);
	let tabContextMenu = $state<{ tabId: string; x: number; y: number } | null>(null);

	function bindPaneMedia(): () => void {
		const narrow = window.matchMedia('max-width: 900px');
		const mobile = window.matchMedia('max-width: 600px');
		const onNarrow = () => {
			if (narrow.matches) leftPaneCollapsed = true;
		};
		const onMobile = () => {
			if (mobile.matches) rightPaneCollapsed = true;
		};
		onNarrow();
		onMobile();
		narrow.addEventListener('change', onNarrow);
		mobile.addEventListener('change', onMobile);
		return () => {
			narrow.removeEventListener('change', onNarrow);
			mobile.removeEventListener('change', onMobile);
		};
	}

	async function loadAnalysisDetail(id: string, signal: AbortSignal): Promise<AnalysisDetail> {
		if (!isUuid(id)) throw new Error('Invalid analysis ID format');
		const cached = queryClient.getQueryData<AnalysisDetail>(analysisQueryKey(id));
		const detail = await fetchAnalysis(id, cached?.etag, { signal });
		if ('notModified' in detail) {
			if (!cached) throw new Error('Analysis cache is empty after 304');
			return cached;
		}
		return detail;
	}

	const analysisQuery = createQuery(() => {
		const id = analysisId ?? '';
		return {
			queryKey: analysisQueryKey(id),
			enabled: !!id,
			staleTime: Infinity,
			refetchOnWindowFocus: false,
			queryFn: ({ signal }) => loadAnalysisDetail(id, signal),
			retry: false
		};
	});

	function applyAnalysisDetail(detail: AnalysisDetail): void {
		analysisStore.applyAnalysis(detail.analysis);
		analysisStore.currentRevision = detail.version;
		lastLoadedVersion = detail.version;
	}

	const currentAnalysis = $derived(analysisStore.current ?? analysisQuery.data?.analysis ?? null);

	// Readiness of the editor itself: the working copy holds this analysis, the
	// pipeline is populated (resolveTabs always yields at least one tab for a
	// loaded analysis, so an empty tab list means "not loaded yet"), and the
	// draft finished hydrating (which waits for the editor lock session).
	const editorReady = $derived.by(() => {
		if (!validAnalysisId || analysisStore.current?.id !== validAnalysisId) return false;
		if (analysisStore.tabs.length === 0) return false;
		return draft.draftLoaded || lock.editorAccessState !== 'pending';
	});

	const editorGate = $derived.by(() => {
		if (editorReady) return 'ready';
		if (analysisQuery.isError && !analysisQuery.data) return 'error';
		return 'loading';
	});
	const analysisFavorite = $derived(
		validAnalysisId ? favoriteStore.isFavorite(validAnalysisId) : false
	);

	function snapBackFromRemoteLock(): void {
		lock.setRemoteSyncPending(true);
		lock.setRemoteSyncFailed(false);

		actions.showDatasourceModal = false;
		showVersionModal = false;
		saveError = '';
		actions.dismissTabError();
		analysisStore.setResourceConfig(null);

		if (storageKey) {
			void idbDelete(storageKey);
		}
		if (analysisQuery.data) {
			const syncAnalysisId = analysisId;
			const syncRouteKey = synchronizedEditorRoute;
			void analysisQuery
				.refetch()
				.then((result) => {
					if (analysisId !== syncAnalysisId || synchronizedEditorRoute !== syncRouteKey) return;
					lock.setRemoteSyncFailed(result.isError);
					if (!result.isError && result.data) {
						applyAnalysisDetail(result.data);
						loadSourceSchemaWhenRouteReady();
					}
				})
				.finally(() => {
					if (analysisId !== syncAnalysisId || synchronizedEditorRoute !== syncRouteKey) return;
					lock.setRemoteSyncPending(false);
					draft.hydrate();
				});
			return;
		}
		lock.setRemoteSyncPending(false);
		draft.hydrate();
	}

	function handleWindowPointerDown(event: PointerEvent) {
		if (!tabContextMenu) return;
		const target = event.target as Node | null;
		const menu = document.querySelector('[data-testid="analysis-tab-context-menu"]');
		if (menu && target && menu.contains(target)) return;
		tabContextMenu = null;
	}

	const analysisTabs = $derived.by(() => {
		const title = analysisStore.current?.name ?? analysisQuery.data?.analysis.name ?? 'Analysis';
		return analysisStore.tabs.map((tab) => ({
			id: tab.id,
			name: `${title} · ${tab.name}`
		}));
	});

	const datasourcesQuery = createQuery(() => ({
		queryKey: ['datasources', ns.value],
		enabled: !ns.switching,
		queryFn: async ({ signal }) => {
			const result = await listDatasources(false, { signal });
			if (result.isErr()) {
				datasourceStore.loaded = true;
				throw new Error(result.error.message);
			}
			datasourceStore.datasources = result.value;
			datasourceStore.loaded = true;
			loadSourceSchemaWhenRouteReady();
			return result.value;
		}
	}));

	const hydrateInferredSchemas = setupInferredSchemaHydrationEffect(() => validAnalysisId);

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
	const previewDatasourceId = $derived(datasourceId ?? schemaKey ?? null);

	const sourceSchemaLoader = setupSourceSchemaLoadingEffect({
		validAnalysisId: () => validAnalysisId,
		analysisId: () => analysisId,
		datasourceId: () => datasourceId,
		schemaKey: () => schemaKey,
		datasources: () => (datasourceStore.loaded ? datasourceStore.datasources : undefined)
	});
	let synchronizedEditorRoute: string | null = null;
	const isLoadingSchema = $derived(sourceSchemaLoader.isLoading());

	function refreshEditorServices(): void {
		hydrateInferredSchemas();
		loadSourceSchemaWhenRouteReady();
	}

	function cancelEditorServices(): void {
		hydrateInferredSchemas.cancel();
		sourceSchemaLoader.cancel();
	}

	function syncEditorRoute(): void {
		const routeKey = `${ns.value}:${analysisId ?? ''}`;
		if (synchronizedEditorRoute === routeKey) return;
		synchronizedEditorRoute = routeKey;
		cancelEditorServices();
		resetForAnalysisId(analysisId);
		lock.sync(validAnalysisId);
		refreshEditorServices();

		const id = analysisId;
		const namespace = ns.value;
		if (!id) return;
		void queryClient
			.ensureQueryData({
				queryKey: analysisQueryKey(id),
				queryFn: ({ signal }) => loadAnalysisDetail(id, signal),
				staleTime: Infinity,
				retry: false
			})
			.then(
				(detail) => {
					if (
						synchronizedEditorRoute !== routeKey ||
						analysisId !== id ||
						!ns.ready ||
						ns.value !== namespace
					)
						return;
					if (analysisStore.current?.id !== id || !analysisStore.isDirty()) {
						applyAnalysisDetail(detail);
					}
					draft.hydrate();
					refreshEditorServices();
				},
				() => {} // The query observer renders load errors.
			);
	}

	function loadSourceSchemaWhenRouteReady(): void {
		const routeKey = `${ns.value}:${analysisId ?? ''}`;
		if (synchronizedEditorRoute !== routeKey) return;
		sourceSchemaLoader.load();
	}

	const currentDatasource = $derived.by(() => {
		if (!datasourceId) return null;
		const data = datasourcesQuery.data;
		if (!data) return null;
		return data.find((ds) => ds.id === datasourceId) ?? null;
	});
	const missingDatasource = $derived.by(() => {
		if (!datasourcesQuery.data) return null;
		const tab = activeTab;
		if (!tab || tab.datasource.analysis_tab_id || !tab.datasource.id) return null;
		if (datasourcesQuery.data.some((datasource) => datasource.id === tab.datasource.id))
			return null;
		return tab.datasource.id;
	});
	const analysisTabName = $derived.by(() => {
		const tab = activeTab;
		if (!tab || !validAnalysisId) return null;
		const sourceTabId = tab.datasource.analysis_tab_id;
		if (!sourceTabId) return null;
		const sourceTab = analysisStore.tabs.find((item) => item.id === String(sourceTabId));
		return sourceTab?.name ?? null;
	});
	const datasourceLabel = $derived(analysisTabName ?? currentDatasource?.name ?? null);

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
		await analysisStore.save().match(
			() => {
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
		saveError = '';
		if (storageKey) {
			draft.flush();
			await idbDelete(storageKey);
		}
		const currentTabId = analysisStore.activeTabId;
		if (analysisStore.current?.id === analysisId && analysisStore.restoreSavedSnapshot()) {
			selectedStepId = null;
			return;
		}
		if (analysisQuery.data) {
			await analysisStore.loadAnalysis(analysisId);
			selectedStepId = null;
			// Restore the tab that was active before discarding changes
			if (currentTabId && analysisStore.tabs.some((t) => t.id === currentTabId)) {
				analysisStore.activeTabId = currentTabId;
			}
		}
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
			persistDraft();
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		}

		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	function handleCloseConfig() {
		selectedStepId = null;
		persistDraft();
	}

	function handleSelectTab(tabId: string) {
		analysisStore.setActiveTab(tabId);
		draft.schedulePersist();
		hydrateInferredSchemas();
		loadSourceSchemaWhenRouteReady();
	}

	onMount(() => {
		syncEditorRoute();
		const unbindPane = bindPaneMedia();
		return () => {
			unbindPane();
		};
	});

	afterNavigate(() => {
		syncEditorRoute();
	});

	async function toggleFavorite() {
		if (!validAnalysisId || !currentAnalysis) return;
		const next = !analysisFavorite;
		const result = next
			? await favoriteAnalysis(validAnalysisId)
			: await unfavoriteAnalysis(validAnalysisId);
		if (result.isErr()) {
			saveError = result.error.message;
			return;
		}
		favoriteStore.apply(validAnalysisId, result.value.is_favorite);
		analysisStore.current = {
			...currentAnalysis,
			is_favorite: result.value.is_favorite
		};
		const isFavorite = result.value.is_favorite;
		queryClient.setQueriesData<Analysis[]>({ queryKey: ['analyses'] }, (current) =>
			current?.map((analysis) =>
				analysis.id === validAnalysisId ? { ...analysis, is_favorite: isFavorite } : analysis
			)
		);
		queryClient.setQueriesData<Analysis[]>({ queryKey: ['favorite-analyses'] }, (current) => {
			if (!current) return current;
			const withoutCurrent = current.filter((analysis) => analysis.id !== validAnalysisId);
			return isFavorite
				? [...withoutCurrent, { ...currentAnalysis, is_favorite: true }]
				: withoutCurrent;
		});
		queryClient.setQueryData<AnalysisDetail>(analysisQueryKey(validAnalysisId), (current) =>
			current ? { ...current, analysis: { ...current.analysis, is_favorite: isFavorite } } : current
		);
	}

	function openDescriptionModal() {
		showDescriptionModal = true;
	}

	function closeDescriptionModal() {
		showDescriptionModal = false;
	}

	function saveDescription(nextDescription: string | null) {
		if (!currentAnalysis) return;
		if ((currentAnalysis.description ?? null) !== nextDescription) {
			analysisStore.update({ description: nextDescription });
			markUnsaved();
		}
	}

	function openVersionModal() {
		showVersionModal = true;
	}

	function handleVersionRestored(restored: { analysis: Analysis; version: string }) {
		schemaStore.reset();
		analysisStore.previews.runs.clear();
		analysisStore.applyAnalysis(restored.analysis);
		analysisStore.currentRevision = restored.version;
		lastLoadedVersion = restored.version;
		selectedStepId = null;
	}

	function openExportModal(tabId: string | null = null) {
		exportScopeTabId = tabId;
		showExportModal = true;
		tabContextMenu = null;
	}

	function handleTabContextMenu(event: MouseEvent, tabId: string) {
		event.preventDefault();
		event.stopPropagation();
		tabContextMenu = { tabId, x: event.clientX, y: event.clientY };
	}
</script>

{#if editorGate !== 'ready'}
	<AnalysisEditorLoadGate
		isLoading={editorGate === 'loading'}
		error={editorGate === 'error' ? analysisQuery.error : null}
	/>
{:else}
	<div
		class={css({
			display: 'flex',
			height: '100%',
			flexDirection: 'column',
			backgroundColor: 'bg.secondary',
			...(isResizingBottomPane ? { userSelect: 'none', cursor: 'ns-resize' } : {})
		})}
	>
		<AnalysisEditorHeader
			tabs={analysisStore.tabs}
			activeTabId={analysisStore.activeTab?.id ?? null}
			titleName={currentAnalysis?.name ?? analysisQuery.data?.analysis.name ?? ''}
			description={currentAnalysis?.description ?? null}
			favorite={analysisFavorite}
			loading={analysisStore.loading}
			{editorReadOnly}
			{editorAccessState}
			{isDirty}
			{isSaving}
			saveButtonState={lock.saveButtonState}
			saveButtonLabel={lock.saveButtonLabel}
			lockButtonLabel={lock.lockButtonLabel}
			lockButtonDisabled={lock.lockButtonDisabled}
			bind:leftPaneCollapsed={() => leftPaneCollapsed, setLeftPaneCollapsed}
			bind:rightPaneCollapsed={() => rightPaneCollapsed, setRightPaneCollapsed}
			bind:configPosition={() => configPosition, setConfigPosition}
			onToggleFavorite={toggleFavorite}
			onEditDescription={openDescriptionModal}
			onCommitTitle={(name) => {
				analysisStore.update({ name });
				markUnsaved();
			}}
			onSelectTab={handleSelectTab}
			onTabContextMenu={handleTabContextMenu}
			onRemoveTab={actions.handleRemoveTab}
			onAddDatasourceTab={() => actions.openDatasourceModal('add')}
			onToggleLock={() => lock.handleToggle()}
			onExport={() => openExportModal(null)}
			onDiscard={discardChanges}
			onSave={handleSave}
			onOpenVersions={openVersionModal}
		/>

		{#if saveError}
			<div class={css({ paddingX: '4', paddingY: '2' })} data-testid="save-error">
				<Callout tone="error">{saveError}</Callout>
			</div>
		{/if}
		{#if missingDatasource}
			<div class={css({ paddingX: '4', paddingY: '2' })} data-testid="analysis-datasource-error">
				<Callout tone="error">
					Datasource not found: {missingDatasource}. Select another datasource for this tab.
				</Callout>
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
			data-editor-access-state={editorAccessState}
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
					onAddStep={actions.handleAddStep}
					onInsertStep={actions.handleInsertStep}
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
					{#key analysisStore.activeTabId}
						<PipelineCanvas
							{buildStore}
							steps={analysisStore.pipeline}
							analysisId={analysisId || undefined}
							datasourceId={previewDatasourceId || undefined}
							datasource={currentDatasource}
							{datasourceLabel}
							tabName={analysisStore.activeTab?.name}
							activeTab={analysisStore.activeTab}
							onStepClick={handleSelectStep}
							onStepDelete={actions.handleDeleteStep}
							onStepToggle={actions.handleToggleStep}
							onInsertStep={actions.handleInsertStep}
							onPasteStep={actions.handlePasteStep}
							onMoveStep={actions.handleMoveStep}
							onChangeDatasource={() => actions.openDatasourceModal('change')}
							onRenameTab={actions.handleRenameSourceTab}
							onDuplicateTab={actions.handleDuplicateActiveTab}
							onResourceConfigChange={persistDraft}
							readOnly={editorReadOnly}
						/>
					{/key}
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
						{#key selectedStepId}
							<StepConfig
								step={selectedStepState}
								schema={schemaStore.calculatedSchema}
								{isLoadingSchema}
								onClose={handleCloseConfig}
								onConfigApply={markUnsaved}
								readOnly={editorReadOnly}
							/>
						{/key}
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
					{#key selectedStepId}
						<StepConfig
							step={selectedStepState}
							schema={schemaStore.calculatedSchema}
							{isLoadingSchema}
							onClose={handleCloseConfig}
							onConfigApply={markUnsaved}
							readOnly={editorReadOnly}
						/>
					{/key}
				</div>
			{/if}
		</div>
	</div>
{/if}

<svelte:window
	onbeforeunload={(e) => {
		if (!isDirty) return;
		e.preventDefault();
	}}
	onpointerdown={handleWindowPointerDown}
/>

{#if actions.tabError}
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
		<Callout tone="error">{actions.tabError}</Callout>
	</div>
{/if}

<DatasourceSelectorModal
	show={actions.showDatasourceModal}
	datasources={datasourcesQuery.data ?? []}
	isLoading={datasourcesQuery.isLoading}
	mode={actions.modalMode}
	sourceType={actions.modalSource}
	allowAnalysis
	{analysisTabs}
	excludeTabId={analysisStore.activeTabId}
	onSelect={actions.handleDatasourceSelect}
	onClose={actions.closeDatasourceModal}
/>

{#if tabContextMenu}
	<div
		class={css({
			position: 'fixed',
			top: '0',
			left: '0',
			zIndex: '1003'
		})}
		style:transform={`translate(${tabContextMenu.x}px, ${tabContextMenu.y}px)`}
		data-testid="analysis-tab-context-menu"
	>
		<button
			class={css({
				display: 'block',
				borderWidth: '1',
				backgroundColor: 'bg.primary',
				paddingX: '3',
				paddingY: '2',
				fontSize: 'xs',
				color: 'fg.primary',
				textAlign: 'left',
				cursor: 'pointer',
				whiteSpace: 'nowrap',
				_hover: { backgroundColor: 'bg.hover' }
			})}
			type="button"
			onclick={() => openExportModal(tabContextMenu?.tabId ?? null)}
			data-testid="analysis-tab-context-export"
		>
			Export as Code
		</button>
	</div>
{/if}

{#key showDescriptionModal}
	<AnalysisEditorDescriptionModal
		open={showDescriptionModal}
		description={currentAnalysis?.description ?? null}
		{editorReadOnly}
		onSave={saveDescription}
		onClose={closeDescriptionModal}
	/>
{/key}

<AnalysisEditorVersionModal
	open={showVersionModal}
	{analysisId}
	{validAnalysisId}
	currentRevision={analysisStore.currentRevision}
	{editorReadOnly}
	onRestored={handleVersionRestored}
	onClose={() => {
		showVersionModal = false;
	}}
/>

{#key showExportModal}
	<AnalysisEditorExportModal
		open={showExportModal}
		{validAnalysisId}
		scopeTabId={exportScopeTabId}
		tabs={analysisTabs}
		onClose={() => {
			showExportModal = false;
			exportScopeTabId = null;
		}}
	/>
{/key}

<DragPreview />
