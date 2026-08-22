<script lang="ts">
	import { page } from '$app/stores';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { MediaQuery } from 'svelte/reactivity';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { BuildStreamStore } from '$lib/stores/build-stream.svelte';
	import { formatPipelineErrors, isUuid, validatePipelineTabs } from '$lib/utils/analysis-tab';
	import { favoriteAnalysis, unfavoriteAnalysis, getAnalysisWithHeaders } from '$lib/api/analysis';
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
		setupEngineDefaultsEffect,
		setupEngineWarmupEffect,
		setupInferredSchemaHydrationEffect,
		setupSourceSchemaLoadingEffect
	} from '$lib/components/analysis-editor/analysis-editor-schema-effects.svelte';
	import { createEditorLockController } from '$lib/components/analysis-editor/analysis-editor-lock.svelte';
	import { createAnalysisEditorActions } from '$lib/components/analysis-editor/analysis-editor-actions.svelte';
	import { createDraftController } from '$lib/components/analysis-editor/analysis-editor-draft.svelte';

	const queryClient = useQueryClient();
	const analysisId = $derived($page.params.id ?? null);
	const validAnalysisId = $derived(analysisId && isUuid(analysisId) ? analysisId : null);
	let lastAnalysisId = $state<string | null>(null);

	let selectedStepId = $state<string | null>(null);
	const buildStore = new BuildStreamStore();
	const selectedStepState = $derived.by(() => {
		if (!selectedStepId) return null;
		return analysisStore.pipeline.find((step) => step.id === selectedStepId) || null;
	});
	let isSaving = $state(false);
	let saveError = $state('');

	// Cleanup: $derived can't clear pending timers on destroy.
	$effect(() => {
		return () => {
			actions.clearTabErrorTimer();
			buildStore.close();
		};
	});

	let isDirty = $state(false);
	let lastLoadedVersion = $state<string | null>(null);

	const lock = createEditorLockController({
		validAnalysisId: () => validAnalysisId,
		getDraftLoaded: () => draft.draftLoaded,
		getIsSaving: () => isSaving,
		getIsDirty: () => isDirty
	});
	lock.startSessionWatcher();
	const editorAccessState = $derived(lock.editorAccessState);
	const lockedByOther = $derived(lock.lockedByOther);
	const lockReadOnly = $derived(lock.lockReadOnly);
	const editorReadOnly = $derived(lock.editorReadOnly);

	function markUnsaved() {
		if (editorReadOnly) return;
		isDirty = true;
	}

	function handleSelectStep(stepId: string) {
		selectedStepId = stepId;
		rightPaneCollapsed = false;
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

	const storageKey = $derived(validAnalysisId ? `analysis-draft:${validAnalysisId}` : null);

	// Timer: $derived can't schedule schema refresh.
	$effect(() => {
		if (!analysisId) return;
		if (lastAnalysisId !== analysisId) {
			analysisStore.reset();
			schemaStore.reset();
			selectedStepId = null;
			lastAnalysisId = analysisId;
		}
		draft.reset();
	});

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
			engineDefaults: analysisStore.engineDefaults,
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
			analysisStore.setEngineDefaults(parsed.engineDefaults);
			selectedStepId = parsed.selectedStepId;
			leftPaneCollapsed = parsed.leftPaneCollapsed;
			rightPaneCollapsed = parsed.rightPaneCollapsed;
			if (parsed.configPosition) configPosition = parsed.configPosition;
			if (parsed.bottomPaneHeight) bottomPaneHeight = parsed.bottomPaneHeight;
			isDirty = true;
		}
	});

	// Subscription: $derived can't sync store side effects.
	$effect(() => {
		if (!analysisId) return;
		isDirty = analysisStore.isDirty();
	});

	let leftPaneCollapsed = $state(false);
	let rightPaneCollapsed = $state(false);
	let configPosition = $state<'right' | 'bottom'>('right');
	let bottomPaneHeight = $state(300);
	let isResizingBottomPane = $state(false);
	let showVersionModal = $state(false);
	let showDescriptionModal = $state(false);
	let showExportModal = $state(false);
	let exportScopeTabId = $state<string | null>(null);
	let tabContextMenu = $state<{ tabId: string; x: number; y: number } | null>(null);

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
			analysisStore.applyAnalysis(result.value.analysis);
			analysisStore.currentRevision = result.value.version;
			lastLoadedVersion = result.value.version;
			isDirty = false;
			return result.value.analysis;
		},
		retry: false
	}));

	const currentAnalysis = $derived(analysisStore.current ?? analysisQuery.data ?? null);
	const analysisFavorite = $derived(
		validAnalysisId ? favoriteStore.isFavorite(validAnalysisId) : false
	);

	let resetForRemoteLock = $state(false);

	// Locking: another owner means this view must snap back to persisted backend state.
	$effect(() => {
		if (!lockedByOther) {
			resetForRemoteLock = false;
			return;
		}
		if (resetForRemoteLock) return;
		resetForRemoteLock = true;
		lock.setRemoteSyncPending(true);
		lock.setRemoteSyncFailed(false);

		actions.showDatasourceModal = false;
		showVersionModal = false;
		saveError = '';
		actions.dismissTabError();
		isDirty = false;
		analysisStore.setResourceConfig(null);

		if (storageKey) {
			void idbDelete(storageKey);
		}
		if (analysisQuery.data) {
			const syncAnalysisId = analysisId;
			void analysisQuery
				.refetch()
				.then((result) => {
					if (analysisId !== syncAnalysisId) return;
					lock.setRemoteSyncFailed(result.isError);
				})
				.finally(() => {
					if (analysisId === syncAnalysisId) lock.setRemoteSyncPending(false);
				});
			return;
		}
		lock.setRemoteSyncPending(false);
	});

	// DOM: context menu dismissal is event-driven and cannot be expressed as derived state.
	$effect(() => {
		if (!tabContextMenu) return;
		const onPointerDown = (event: PointerEvent) => {
			const target = event.target as Node | null;
			const menu = document.querySelector('[data-testid="analysis-tab-context-menu"]');
			if (menu && target && menu.contains(target)) {
				return;
			}
			tabContextMenu = null;
		};
		window.addEventListener('pointerdown', onPointerDown);
		return () => window.removeEventListener('pointerdown', onPointerDown);
	});

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

	setupEngineDefaultsEffect(() => validAnalysisId);
	setupEngineWarmupEffect(() => validAnalysisId);
	setupInferredSchemaHydrationEffect(() => validAnalysisId);

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

	const isLoadingSchemaGetter = setupSourceSchemaLoadingEffect({
		validAnalysisId: () => validAnalysisId,
		analysisId: () => analysisId,
		datasourceId: () => datasourceId,
		schemaKey: () => schemaKey,
		datasources: () => datasourcesQuery.data
	});
	const isLoadingSchema = $derived(isLoadingSchemaGetter());

	const currentDatasource = $derived.by(() => {
		if (!datasourceId) return null;
		const data = datasourcesQuery.data;
		if (!data) return null;
		return data.find((ds) => ds.id === datasourceId) ?? null;
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
		void queryClient.invalidateQueries({ queryKey: ['analyses'] });
		void queryClient.invalidateQueries({ queryKey: ['favorite-analyses'] });
		void queryClient.invalidateQueries({ queryKey: ['analysis', validAnalysisId] });
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
		isDirty = false;
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

{#if analysisQuery.isLoading || analysisQuery.isError}
	<AnalysisEditorLoadGate isLoading={analysisQuery.isLoading} error={analysisQuery.error} />
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
		<AnalysisEditorHeader
			tabs={analysisStore.tabs}
			activeTabId={analysisStore.activeTab?.id ?? null}
			titleName={currentAnalysis?.name ?? analysisQuery.data.name}
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
			bind:leftPaneCollapsed
			bind:rightPaneCollapsed
			bind:configPosition
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
							schema={schemaStore.calculatedSchema}
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
						schema={schemaStore.calculatedSchema}
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
	onbeforeunload={(e) => {
		if (!isDirty) return;
		e.preventDefault();
	}}
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

<AnalysisEditorDescriptionModal
	open={showDescriptionModal}
	description={currentAnalysis?.description ?? null}
	{editorReadOnly}
	onSave={saveDescription}
	onClose={closeDescriptionModal}
/>

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

<DragPreview />
