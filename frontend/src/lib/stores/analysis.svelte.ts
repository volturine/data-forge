import type { Analysis, AnalysisTab, AnalysisUpdate, PipelineStep } from '$lib/types/analysis';

import type { SchemaInfo } from '$lib/types/datasource';
import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
import type { Schema } from '$lib/types/schema';
import { getAnalysisWithHeaders, updateAnalysis } from '$lib/api/analysis';
import {
	buildOutputConfig,
	ensureTabDefaults,
	validatePipelineTabs
} from '$lib/utils/analysis-tab';
import { normalizeDtype } from '$lib/utils/transform';
import { normalizeConfig } from '$lib/utils/step-config-defaults';
import { track } from '$lib/utils/audit-log';
import { schemaStore } from '$lib/stores/schema.svelte';
import { getLockPayload } from '$lib/stores/lockManager.svelte';
import { SvelteMap } from 'svelte/reactivity';
import { ResultAsync, err, ok } from 'neverthrow';
import type { ApiError } from '$lib/api/client';
import { idbGet, idbSet } from '$lib/utils/indexeddb';

function cloneConfig(config: unknown): Record<string, unknown> {
	return JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
}

async function loadPreviewRuns(map: SvelteMap<string, boolean>): Promise<void> {
	const stored = await idbGet<Array<[string, boolean]>>('analysis_preview_runs');
	if (!stored) return;
	for (const [key, value] of stored) {
		map.set(key, value);
	}
}

function savePreviewRuns(map: SvelteMap<string, boolean>): void {
	const entries = Array.from(map.entries());
	void idbSet('analysis_preview_runs', entries);
}

export class AnalysisStore {
	current = $state<Analysis | null>(null);
	tabs = $state<AnalysisTab[]>([]);
	savedTabs = $state<AnalysisTab[]>([]);
	activeTabId = $state<string | null>(null);
	sourceSchemas = $state(new SvelteMap<string, SchemaInfo>());
	resourceConfig = $state<EngineResourceConfig | null>(null);
	engineDefaults = $state<EngineDefaults | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	loadId = $state(0);
	lastSaved = $state<{ name: string; description: string | null } | null>(null);
	previewRuns = $state(new SvelteMap<string, boolean>());

	constructor() {
		void loadPreviewRuns(this.previewRuns);
	}

	setPreviewRun(key: string, value: boolean): void {
		this.previewRuns.set(key, value);
		savePreviewRuns(this.previewRuns);
	}

	activeTab: AnalysisTab | null = $derived(
		this.tabs.find((tab) => tab.id === this.activeTabId) ?? this.tabs[0] ?? null
	);

	activeSchemaKey = $derived.by(() => {
		const tab = this.activeTab;
		const analysisId = this.current?.id ?? null;
		if (!tab || !analysisId) return null;
		const sourceTabId = tab.datasource.analysis_tab_id;
		if (sourceTabId) {
			return `output:${analysisId}:${String(sourceTabId)}`;
		}
		return tab.datasource.id;
	});

	pipeline = $derived(this.activeTab?.steps ?? []);

	calculatedSchema = $derived.by(() => {
		if (!this.pipeline.length || !this.sourceSchemas.size) return null;

		const sourceSchema = this.activeSchemaKey
			? this.sourceSchemas.get(this.activeSchemaKey)
			: this.sourceSchemas.values().next().value;
		if (!sourceSchema) return null;

		const baseSchema: Schema = {
			columns: sourceSchema.columns.map((col) => ({
				name: col.name,
				dtype: normalizeDtype(col.dtype) ?? col.dtype,
				nullable: col.nullable
			})),
			row_count: sourceSchema.row_count
		};

		return schemaStore.getLastOutput() ?? baseSchema;
	});

	applyAnalysis(analysis: Analysis): void {
		const previousId = this.current?.id ?? null;
		this.current = analysis;
		this.lastSaved = { name: analysis.name, description: analysis.description ?? null };
		if (previousId !== analysis.id) {
			this.activeTabId = null;
			this.sourceSchemas.clear();
		}
		this.resolveTabs(analysis);
	}

	loadAnalysis(id: string): ResultAsync<void, ApiError> {
		const token = this.loadId + 1;
		this.loadId = token;
		this.reset();
		this.loading = true;
		this.error = null;

		return getAnalysisWithHeaders(id)
			.andThen(({ analysis, version }) => {
				if (this.loadId !== token) return ok(undefined);
				this.current = { ...analysis, version };
				this.lastSaved = { name: analysis.name, description: analysis.description ?? null };
				this.resolveTabs(analysis);
				return ok(undefined);
			})
			.mapErr((error) => {
				if (this.loadId !== token) return error;
				this.error = error.message;
				this.loading = false;
				return error;
			});
	}

	private resolveTabs(analysis: Analysis): void {
		const tabs = analysis.tabs.length
			? analysis.tabs
			: (analysis.pipeline_definition as { tabs?: AnalysisTab[] })?.tabs;
		if (tabs?.length) {
			this.applyTabs(tabs);
			return;
		}
		this.applyTabs(this.buildTabs([]));
	}

	isDirty(): boolean {
		if (!this.current) return false;
		const savedMeta = this.lastSaved ?? {
			name: this.current.name,
			description: this.current.description ?? null
		};
		if (this.current.name !== savedMeta.name) return true;
		if ((this.current.description ?? null) !== savedMeta.description) return true;
		if (this.tabs.length !== this.savedTabs.length) return true;
		for (let i = 0; i < this.tabs.length; i += 1) {
			const currentTab = this.tabs[i];
			const savedTab = this.savedTabs[i];
			if (!savedTab) return true;
			if (currentTab.id !== savedTab.id) return true;
			if (currentTab.name !== savedTab.name) return true;
			if ((currentTab.parent_id ?? null) !== (savedTab.parent_id ?? null)) return true;
			if (currentTab.datasource.id !== savedTab.datasource.id) return true;
			if (currentTab.datasource.analysis_tab_id !== savedTab.datasource.analysis_tab_id)
				return true;
			const currentConfig = JSON.stringify(currentTab.datasource.config);
			const savedConfig = JSON.stringify(savedTab.datasource.config);
			if (currentConfig !== savedConfig) return true;
			const currentOutput = JSON.stringify(currentTab.output ?? {});
			const savedOutput = JSON.stringify(savedTab.output ?? {});
			if (currentOutput !== savedOutput) return true;
			const currentSteps = currentTab.steps;
			const savedSteps = savedTab.steps;
			if (currentSteps.length !== savedSteps.length) return true;
			for (let j = 0; j < currentSteps.length; j += 1) {
				const currentStep = currentSteps[j];
				const savedStep = savedSteps[j];
				if (!savedStep) return true;
				if (currentStep.id !== savedStep.id) return true;
				if (currentStep.type !== savedStep.type) return true;
				const currentDepends = currentStep.depends_on ?? [];
				const savedDepends = savedStep.depends_on ?? [];
				if (currentDepends.length !== savedDepends.length) return true;
				if (currentDepends.some((d, k) => d !== savedDepends[k])) return true;
				const currentConfig = JSON.stringify(currentStep.config ?? {});
				const savedConfig = JSON.stringify(savedStep.config ?? {});
				if (currentConfig !== savedConfig) return true;
				const currentApplied = currentStep.is_applied !== false;
				const savedApplied = savedStep.is_applied !== false;
				if (currentApplied !== savedApplied) return true;
			}
		}
		return false;
	}

	private logStep(action: string, step: PipelineStep, meta?: Record<string, unknown>): void {
		track({
			event: 'analysis_step',
			action,
			target: step.type,
			meta: {
				analysis_id: this.current?.id ?? null,
				tab_id: this.activeTabId,
				step_id: step.id,
				...meta
			}
		});
	}

	addStep(step: PipelineStep): void {
		if (!this.activeTab) return;
		const steps = this.activeTab.steps;
		const parentId = steps.at(-1)?.id ?? null;
		step.depends_on = parentId ? [parentId] : [];
		const newSteps = [...steps, step].map((item) => ({
			...item,
			config: cloneConfig(item.config)
		}));
		this.updateTabSteps(this.activeTab.id, newSteps);
		this.logStep('add', step, { index: newSteps.length - 1 });
	}

	setTabs(tabs: AnalysisTab[]): void {
		this.tabs = tabs;
		if (this.activeTabId && tabs.some((tab) => tab.id === this.activeTabId)) {
			return;
		}
		this.activeTabId = tabs[0]?.id ?? null;
	}

	private applyTabs(tabs: AnalysisTab[]): void {
		const sanitized = this.normalizeTabSteps(tabs).map((tab, i) => ensureTabDefaults(tab, i));
		this.setTabs(sanitized);
		this.savedTabs = sanitized;
		this.loading = false;
		this.error = null;
	}

	private normalizeTabSteps(tabs: AnalysisTab[]): AnalysisTab[] {
		return tabs.map((tab) => ({
			...tab,
			datasource: { ...tab.datasource, config: { ...tab.datasource.config } },
			steps: this.normalizeSteps(tab.steps)
		}));
	}

	private normalizeSteps(steps: PipelineStep[]): PipelineStep[] {
		if (!steps.length) return steps;
		const hasDependencies = steps.some((step) => (step.depends_on ?? []).length > 0);
		return steps.map((step, index) => {
			const depends_on = hasDependencies
				? step.depends_on
				: index === 0
					? []
					: steps[index - 1]?.id
						? [steps[index - 1].id]
						: [];
			return {
				...step,
				type: step.type.startsWith('plot_') ? 'chart' : step.type,
				config: normalizeConfig(step.type, step.config as Record<string, unknown>) as Record<
					string,
					unknown
				>,
				depends_on,
				is_applied: step.is_applied !== false
			};
		});
	}

	setActiveTab(id: string): void {
		this.activeTabId = id;
	}

	addTab(tab: AnalysisTab): void {
		const newTab = { ...tab, steps: tab.steps ?? [] };
		this.tabs = [...this.tabs, newTab];
		this.activeTabId = newTab.id;
	}

	removeTab(id: string): void {
		this.tabs = this.tabs.filter((tab) => tab.id !== id);
		if (this.activeTabId === id) {
			this.activeTabId = this.tabs[0]?.id ?? null;
		}
	}

	updateTab(id: string, updates: Partial<AnalysisTab>): void {
		this.tabs = this.tabs.map((tab) => (tab.id === id ? { ...tab, ...updates } : tab));
	}

	updateTabSteps(tabId: string, steps: PipelineStep[]): void {
		this.tabs = this.tabs.map((tab) => (tab.id === tabId ? { ...tab, steps } : tab));
	}

	insertStep(
		step: PipelineStep,
		index: number,
		parentId: string | null,
		nextId: string | null
	): boolean {
		if (!this.activeTab) return false;

		const nextPipeline = [...this.activeTab.steps];
		step.depends_on = parentId ? [parentId] : [];
		const isChart = step.type === 'chart' || step.type.startsWith('plot_');

		if (nextId) {
			const nextStepIndex = nextPipeline.findIndex((item) => item.id === nextId);
			if (nextStepIndex < 0) return false;
			if (!isChart) {
				const nextStep = nextPipeline[nextStepIndex];
				const nextDeps = nextStep.depends_on ?? [];
				if (nextDeps.length > 1) return false;
				if (parentId && nextDeps.length > 0 && nextDeps[0] !== parentId) return false;
				if (!parentId && nextDeps.length > 0) return false;
				nextPipeline[nextStepIndex] = { ...nextStep, depends_on: [step.id] };
			}
		}

		nextPipeline.splice(index, 0, step);
		const nextSteps = nextPipeline.map((item) => ({ ...item, config: cloneConfig(item.config) }));
		this.updateTabSteps(this.activeTab.id, nextSteps);
		this.logStep('insert', step, { index });
		return true;
	}

	addBranchStep(step: PipelineStep, parentId: string | null): void {
		if (!this.activeTab) return;
		step.depends_on = parentId ? [parentId] : [];
		const newSteps = [...this.activeTab.steps, step].map((item) => ({
			...item,
			config: cloneConfig(item.config)
		}));
		this.updateTabSteps(this.activeTab.id, newSteps);
		this.logStep('branch', step, { parent_id: parentId });
	}

	updateStep(id: string, updates: Partial<PipelineStep>): void {
		if (!this.activeTab) return;
		const nextPipeline = this.activeTab.steps.map((step) =>
			step.id === id
				? {
						...step,
						...updates,
						config: cloneConfig(updates.config ?? step.config)
					}
				: step
		);
		this.updateTabSteps(this.activeTab.id, nextPipeline);
	}

	updateStepConfig(id: string, config: Record<string, unknown>): void {
		if (!this.activeTab) return;
		const safeConfig = cloneConfig(config);
		const nextPipeline = this.activeTab.steps.map((step) =>
			step.id === id ? { ...step, config: safeConfig } : step
		);
		this.updateTabSteps(this.activeTab.id, nextPipeline);
		const step = nextPipeline.find((item) => item.id === id);
		if (!step) return;
		const keys = Object.keys(safeConfig);
		this.logStep('update', step, { keys, count: keys.length });
		const analysisId = this.current?.id ?? null;
		const datasourceId = this.activeTab.datasource.id;
		if (!analysisId) return;
		const configSnapshot = this.activeTab.datasource.config as Record<string, unknown>;
		const snapshotId = (configSnapshot.snapshot_id as string | null | undefined) ?? null;
		const snapshotMs = (configSnapshot.snapshot_timestamp_ms as number | null | undefined) ?? null;
		const snapshotKey = `${snapshotId ?? 'latest'}:${snapshotMs ?? 0}`;
		const edges: Record<string, string[]> = {};
		for (const item of nextPipeline) {
			for (const dep of item.depends_on ?? []) {
				(edges[dep] ??= []).push(item.id);
			}
		}
		const reachable: Record<string, true> = {};
		const stack = [id];
		while (stack.length) {
			const current = stack.pop();
			if (!current) continue;
			if (reachable[current]) continue;
			reachable[current] = true;
			const next = edges[current] ?? [];
			for (const child of next) {
				if (!reachable[child]) stack.push(child);
			}
		}
		for (const item of nextPipeline) {
			if (item.type !== 'view') continue;
			if (!reachable[item.id]) continue;
			const rowLimit = typeof item.config?.rowLimit === 'number' ? item.config.rowLimit : 100;
			const runKey = `${analysisId}:${datasourceId}:${snapshotKey}:${rowLimit}:${item.id}`;
			this.setPreviewRun(runKey, true);
		}
		// Invalidate previews in dependent tabs that use this tab as input
		const activeTabId = this.activeTab.id;
		for (const tab of this.tabs) {
			if (tab.id === activeTabId) continue;
			const sourceTabId = tab.datasource.analysis_tab_id;
			if (String(sourceTabId ?? '') !== activeTabId) continue;
			const depDatasourceId = tab.datasource.id;
			const depConfig = tab.datasource.config as Record<string, unknown>;
			const depSnapshotId = (depConfig.snapshot_id as string | null | undefined) ?? null;
			const depSnapshotMs = (depConfig.snapshot_timestamp_ms as number | null | undefined) ?? null;
			const depSnapshotKey = `${depSnapshotId ?? 'latest'}:${depSnapshotMs ?? 0}`;
			for (const item of tab.steps) {
				if (item.type !== 'view') continue;
				const rowLimit = typeof item.config?.rowLimit === 'number' ? item.config.rowLimit : 100;
				const runKey = `${analysisId}:${depDatasourceId}:${depSnapshotKey}:${rowLimit}:${item.id}`;
				this.setPreviewRun(runKey, true);
			}
		}
	}

	removeStep(id: string): void {
		if (!this.activeTab) return;

		const steps = this.activeTab.steps;
		const removedStep = steps.find((step) => step.id === id);
		if (!removedStep) return;

		const removedParentId = removedStep.depends_on?.[0] ?? null;

		const nextPipeline = steps
			.filter((step) => step.id !== id)
			.map((step) => {
				const deps = step.depends_on ?? [];
				if (deps.includes(id)) {
					return { ...step, depends_on: removedParentId ? [removedParentId] : [] };
				}
				return step;
			});

		this.updateTabSteps(this.activeTab.id, nextPipeline);
		this.logStep('remove', removedStep, { parent_id: removedParentId });
	}

	reorderSteps(fromIndex: number, toIndex: number): void {
		if (!this.activeTab) return;
		const steps = [...this.activeTab.steps];
		const [moved] = steps.splice(fromIndex, 1);
		const movedCopy = { ...moved, config: cloneConfig(moved.config) };
		steps.splice(toIndex, 0, movedCopy);
		this.updateTabSteps(this.activeTab.id, steps);
		this.logStep('reorder', movedCopy, { from: fromIndex, to: toIndex });
	}

	/**
	 * Move an existing step to a new position in the pipeline.
	 * Updates dependency chains accordingly.
	 */
	moveStep(
		stepId: string,
		toIndex: number,
		newParentId: string | null,
		newNextId: string | null
	): boolean {
		if (!this.activeTab) return false;

		const steps = [...this.activeTab.steps];
		const fromIndex = steps.findIndex((s) => s.id === stepId);
		if (fromIndex < 0) return false;

		const movingStep = { ...steps[fromIndex] };
		const oldDeps = movingStep.depends_on ?? [];
		const oldParentId = oldDeps[0] ?? null;
		const isChart = movingStep.type === 'chart' || movingStep.type.startsWith('plot_');

		// Find the step that depended on the moving step (if any)
		const dependentStep = isChart ? null : steps.find((s) => s.depends_on?.includes(stepId));

		// Remove from old position
		steps.splice(fromIndex, 1);

		// Update the dependent step to point to the moving step's old parent
		if (dependentStep) {
			const depIndex = steps.findIndex((s) => s.id === dependentStep.id);
			if (depIndex >= 0) {
				steps[depIndex] = {
					...steps[depIndex],
					depends_on: oldParentId ? [oldParentId] : []
				};
			}
		}

		// Update moving step's depends_on
		movingStep.depends_on = newParentId ? [newParentId] : [];

		// Calculate actual insert index (account for removal shifting indices)
		const actualToIndex = fromIndex < toIndex ? toIndex - 1 : toIndex;

		// Insert at new position
		steps.splice(actualToIndex, 0, movingStep);

		// Update the next step to depend on the moved step
		if (newNextId && !isChart) {
			const nextIndex = steps.findIndex((s) => s.id === newNextId);
			if (nextIndex >= 0) {
				steps[nextIndex] = {
					...steps[nextIndex],
					depends_on: [stepId]
				};
			}
		}

		this.updateTabSteps(this.activeTab.id, steps);
		this.logStep('move', movingStep, {
			from: fromIndex,
			to: actualToIndex,
			parent_id: newParentId
		});
		return true;
	}

	save(): ResultAsync<void, ApiError> {
		if (!this.current) {
			this.loading = false;
			return err({
				type: 'parse' as const,
				message: 'No analysis loaded'
			}) as unknown as ResultAsync<void, ApiError>;
		}

		this.loading = true;
		this.error = null;
		const lockPayload = getLockPayload(this.current.id);
		if (!lockPayload) {
			this.loading = false;
			return err({
				type: 'parse' as const,
				message: 'Editing lock required'
			}) as unknown as ResultAsync<void, ApiError>;
		}

		const errors = validatePipelineTabs(this.tabs);
		if (errors.length) {
			this.loading = false;
			return err({
				type: 'parse' as const,
				message: errors[0]?.message ?? 'Pipeline validation failed'
			}) as unknown as ResultAsync<void, ApiError>;
		}
		const update: AnalysisUpdate = {
			name: this.current.name,
			description: this.current.description,
			tabs: this.tabs,
			client_id: lockPayload.clientId,
			lock_token: lockPayload.lockToken
		};

		return updateAnalysis(this.current.id, update)
			.andThen((updated) => {
				const version = this.current?.version ?? null;
				this.current = { ...updated, version };
				this.lastSaved = { name: updated.name, description: updated.description ?? null };
				const tabs = updated.tabs ?? [];
				if (tabs.length) {
					const sanitized = this.normalizeTabSteps(tabs).map((tab, i) => ensureTabDefaults(tab, i));
					this.tabs = sanitized;
					this.savedTabs = sanitized;
					if (!this.activeTabId || !tabs.some((tab) => tab.id === this.activeTabId)) {
						this.activeTabId = this.tabs[0]?.id ?? null;
					}
				}
				this.loading = false;
				return ok(undefined);
			})
			.mapErr((error) => {
				this.error = error.message;
				this.loading = false;
				return error;
			});
	}

	update(updates: { name?: string; description?: string }): void {
		if (!this.current) return;
		this.current = { ...this.current, ...updates };
	}

	setSourceSchema(datasourceId: string, schema: SchemaInfo): void {
		this.sourceSchemas.set(datasourceId, schema);
	}

	clearSourceSchemas(): void {
		this.sourceSchemas.clear();

		this.error = null;
		this.loading = false;
	}

	setResourceConfig(config: EngineResourceConfig | null): void {
		this.resourceConfig = config;
	}

	setEngineDefaults(defaults: EngineDefaults | null): void {
		this.engineDefaults = defaults;
	}

	reset(): void {
		this.current = null;
		this.tabs = [];
		this.savedTabs = [];
		this.activeTabId = null;
		this.sourceSchemas.clear();
		this.resourceConfig = null;
		this.engineDefaults = null;
		this.lastSaved = null;
		this.loading = false;
		this.error = null;
	}

	buildTabs(datasourceIds: string[]): AnalysisTab[] {
		return datasourceIds.map((datasourceId, index) => {
			const name = `Source ${index + 1}`;
			return {
				id: `tab-${datasourceId}`,
				name,
				parent_id: null,
				datasource: {
					id: datasourceId,
					analysis_tab_id: null,
					config: { branch: 'master' }
				},
				output: buildOutputConfig({ name, branch: 'master' }),
				steps: []
			};
		});
	}
}

export type AnalysisStoreApi = {
	resourceConfig: EngineResourceConfig | null;
	engineDefaults: EngineDefaults | null;
	setResourceConfig: (config: EngineResourceConfig | null) => void;
	setEngineDefaults: (defaults: EngineDefaults | null) => void;
	insertStep: (
		step: PipelineStep,
		index: number,
		parentId: string | null,
		nextId: string | null
	) => boolean;
	addBranchStep: (step: PipelineStep, parentId: string | null) => void;
};

export const analysisStore = new AnalysisStore();
