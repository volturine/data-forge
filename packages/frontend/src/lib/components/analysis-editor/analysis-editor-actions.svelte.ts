import { analysisStore } from '$lib/stores/analysis.svelte';
import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
import { getDefaultConfig } from '$lib/utils/step-config-defaults';
import { buildOutputConfig, generateOutputName } from '$lib/utils/analysis-tab';
import { isChartStep } from '$lib/components/pipeline/utils';
import { nowEpochMs } from '$lib/utils/temporal';
import { uuid } from '$lib/utils/uuid';
import { cloneJson } from '$lib/utils/json';
import type { ClipboardStep } from '$lib/components/pipeline/PipelineCanvas.svelte';
import type { DropTarget } from '$lib/stores/drag.svelte';

export type AnalysisEditorActionsDeps = {
	analysisId: () => string | null;
	editorReadOnly: () => boolean;
	activeTab: () => AnalysisTab | null;
	schemaKey: () => string | undefined;
	markUnsaved: () => void;
	selectStep: (stepId: string | null) => void;
	clearSelectedStep: (stepId: string) => void;
	expandRightPane: () => void;
};

export function createAnalysisEditorActions(deps: AnalysisEditorActionsDeps) {
	function buildStep(type: string): PipelineStep {
		const base: PipelineStep = {
			id: uuid(),
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

	function buildInitialSteps(): PipelineStep[] {
		const step = buildStep('view');
		step.depends_on = [];
		return [step];
	}

	function handleAddStep(type: string) {
		if (deps.editorReadOnly()) return;
		const step = buildStep(type);
		analysisStore.addStep(step);
		deps.selectStep(step.id);
		deps.expandRightPane();
		deps.markUnsaved();
	}

	function handleInsertStep(type: string, target: DropTarget) {
		if (deps.editorReadOnly()) return;
		const step = buildStep(type);
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			deps.selectStep(step.id);
			deps.expandRightPane();
			deps.markUnsaved();
		}
	}

	function handlePasteStep(payload: ClipboardStep, target: DropTarget) {
		if (deps.editorReadOnly()) return;
		const step: PipelineStep = {
			id: uuid(),
			type: payload.type,
			config: cloneJson(payload.config),
			depends_on: [],
			is_applied: payload.is_applied
		};
		const inserted = analysisStore.insertStep(step, target.index, target.parentId, target.nextId);
		if (inserted) {
			deps.selectStep(step.id);
			deps.expandRightPane();
			deps.markUnsaved();
		}
	}

	function handleMoveStep(stepId: string, target: DropTarget) {
		if (deps.editorReadOnly()) return;
		analysisStore.moveStep(stepId, target.index, target.parentId, target.nextId);
		deps.markUnsaved();
	}

	function handleDeleteStep(stepId: string) {
		if (deps.editorReadOnly()) return;
		analysisStore.removeStep(stepId);
		deps.clearSelectedStep(stepId);
		deps.markUnsaved();
	}

	function handleToggleStep(stepId: string) {
		if (deps.editorReadOnly()) return;
		const step = analysisStore.pipeline.find((item) => item.id === stepId);
		if (!step) return;
		const next = step.is_applied === false;
		analysisStore.updateStep(stepId, { is_applied: next } as Partial<PipelineStep>);
		deps.markUnsaved();
	}

	function handleAddTab(datasourceId: string, name: string) {
		if (deps.editorReadOnly()) return;
		const tabId = `tab-${datasourceId}-${nowEpochMs()}`;
		const output = buildOutputConfig({
			outputId: uuid(),
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
		closeDatasourceModalOnly();
		deps.markUnsaved();
	}

	function handleAddAnalysisTab(
		datasourceId: string,
		sourceAnalysisId: string,
		name: string,
		sourceTabId: string | null
	) {
		if (deps.editorReadOnly()) return;
		if (
			modalMode === 'change' &&
			deps.analysisId() &&
			sourceAnalysisId === deps.analysisId() &&
			sourceTabId === analysisStore.activeTabId
		) {
			flashTabError('Select a different tab to avoid using the current tab as its own source.');
			return;
		}
		const tabId = `tab-analysis-${datasourceId}-${nowEpochMs()}`;
		const output = buildOutputConfig({
			outputId: uuid(),
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
		if (deps.analysisId() && sourceTabId) {
			analysisStore.sourceSchemas.delete(`output:${deps.analysisId()}:${String(sourceTabId)}`);
		}
		closeDatasourceModalOnly();
		deps.markUnsaved();
	}

	function handleChangeDatasource(datasourceId: string) {
		if (deps.editorReadOnly()) return;
		const active = deps.activeTab();
		if (!active) return;
		analysisStore.updateTab(active.id, {
			datasource: { ...active.datasource, id: datasourceId, analysis_tab_id: null }
		});
		const schemaKey = deps.schemaKey();
		if (schemaKey) analysisStore.sourceSchemas.delete(schemaKey);
		closeDatasourceModalOnly();
		deps.markUnsaved();
	}

	function handleDatasourceSelect(
		datasourceId: string,
		name: string,
		source: 'datasource' | 'analysis'
	) {
		if (deps.editorReadOnly()) return;
		if (source === 'analysis') {
			const analysisId = deps.analysisId();
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
				const active = deps.activeTab();
				if (!active) return;
				analysisStore.updateTab(active.id, {
					datasource: {
						...active.datasource,
						id: outputId,
						analysis_tab_id: analysisTabId
					}
				});
				const schemaKey = deps.schemaKey();
				if (schemaKey) analysisStore.sourceSchemas.delete(schemaKey);
				closeDatasourceModalOnly();
				deps.markUnsaved();
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
		if (deps.editorReadOnly()) return;
		analysisStore.removeTab(tabId);
		deps.markUnsaved();
	}

	function handleDuplicateTab(tabId: string) {
		if (deps.editorReadOnly()) return;
		const duplicated = analysisStore.duplicateTab(tabId);
		if (!duplicated) {
			flashTabError(
				'Failed to duplicate tab because the source pipeline dependencies are invalid.'
			);
			return;
		}
		deps.markUnsaved();
	}

	function handleDuplicateActiveTab() {
		const currentTabId = analysisStore.activeTab?.id;
		if (!currentTabId) return;
		handleDuplicateTab(currentTabId);
	}

	function handleRenameSourceTab(nextName: string) {
		if (deps.editorReadOnly()) return;
		const active = deps.activeTab();
		if (!active) return;
		const trimmed = nextName.trim();
		if (!trimmed || trimmed === active.name) return;
		analysisStore.updateTab(active.id, { name: trimmed });
		deps.markUnsaved();
	}

	let modalMode = $state<'add' | 'change'>('add');
	let modalSource = $state<'datasource' | 'analysis'>('datasource');

	function openDatasourceModal(mode: 'add' | 'change' = 'add') {
		if (deps.editorReadOnly()) return;
		modalMode = mode;
		const sourceType = deps.activeTab()?.datasource.analysis_tab_id ? 'analysis' : 'datasource';
		modalSource = sourceType;
		showDatasourceModal = true;
	}

	let showDatasourceModal = $state(false);

	function closeDatasourceModalOnly() {
		showDatasourceModal = false;
		tabError = '';
	}

	let tabErrorTimer: number | null = null;
	let tabError = $state('');

	function flashTabError(message: string) {
		tabError = message;
		if (tabErrorTimer !== null) window.clearTimeout(tabErrorTimer);
		tabErrorTimer = window.setTimeout(() => {
			tabError = '';
			tabErrorTimer = null;
		}, 5000);
	}

	function dismissTabError() {
		tabError = '';
	}

	function clearTabErrorTimer() {
		if (tabErrorTimer !== null) window.clearTimeout(tabErrorTimer);
	}

	return {
		buildStep,
		buildInitialSteps,
		handleAddStep,
		handleInsertStep,
		handlePasteStep,
		handleMoveStep,
		handleDeleteStep,
		handleToggleStep,
		handleAddTab,
		handleAddAnalysisTab,
		handleChangeDatasource,
		handleDatasourceSelect,
		handleRemoveTab,
		handleDuplicateTab,
		handleDuplicateActiveTab,
		handleRenameSourceTab,
		openDatasourceModal,
		closeDatasourceModal: closeDatasourceModalOnly,
		flashTabError,
		dismissTabError,
		clearTabErrorTimer,
		get modalMode() {
			return modalMode;
		},
		get modalSource() {
			return modalSource;
		},
		get showDatasourceModal() {
			return showDatasourceModal;
		},
		set showDatasourceModal(value: boolean) {
			showDatasourceModal = value;
		},
		get tabError() {
			return tabError;
		}
	};
}
