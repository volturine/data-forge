import type { Analysis, AnalysisTab, AnalysisUpdate, PipelineStep } from '$lib/types/analysis';

import type { SchemaInfo } from '$lib/types/datasource';
import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
import type { Schema } from '$lib/types/schema';
import { getAnalysisWithHeaders, updateAnalysis } from '$lib/api/analysis';
import {
	buildOutputConfig,
	ensureTabDefaults,
	generateOutputName,
	validatePipelineTabs
} from '$lib/utils/analysis-tab';
import { normalizeDtype } from '$lib/utils/transform';
import { normalizeConfig } from '$lib/utils/step-config-defaults';
import { isChartStep, normalizeStepType } from '$lib/components/pipeline/utils';
import { track } from '$lib/utils/audit-log';
import { cloneJson, isRecord } from '$lib/utils/json';
import { uuid } from '$lib/utils/uuid';
import { schemaStore } from '$lib/stores/schema.svelte';
import { SvelteMap } from 'svelte/reactivity';
import { ResultAsync, errAsync, ok } from 'neverthrow';
import type { ApiError } from '$lib/api/client';
import { idbGet, idbSet } from '$lib/utils/indexeddb';

function cloneConfig<T extends Record<string, unknown>>(config: T): T {
	return cloneJson(config);
}

function slugifyOutputName(name: string): string {
	const trimmed = name.trim();
	if (!trimmed) return 'export';
	return trimmed.replace(/\s+/g, '_').toLowerCase();
}

function nextDuplicateTabName(tabs: AnalysisTab[], sourceName: string): string {
	const base = `${sourceName} Copy`;
	const existing = new Set(tabs.map((tab) => tab.name));
	if (!existing.has(base)) return base;
	let suffix = 2;
	while (existing.has(`${base} ${suffix}`)) suffix += 1;
	return `${base} ${suffix}`;
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
	previewPaused = $state(false);

	constructor() {
		void loadPreviewRuns(this.previewRuns);
	}

	setPreviewRun(key: string, value: boolean): void {
		this.previewRuns.set(key, value);
		savePreviewRuns(this.previewRuns);
	}

	setPreviewPaused(value: boolean): void {
		this.previewPaused = value;
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
		const tabs = (analysis.pipeline_definition as { tabs?: AnalysisTab[] })?.tabs;
		if (tabs?.length) {
			this.applyTabs(tabs);
			return;
		}
		this.applyTabs(this.buildTabs([]));
	}

	isDirty(): boolean {
		if (!this.current) return false;
		const saved = this.lastSaved ?? {
			name: this.current.name,
			description: this.current.description ?? null
		};
		if (
			this.current.name !== saved.name ||
			(this.current.description ?? null) !== saved.description
		)
			return true;
		return JSON.stringify(this.tabs) !== JSON.stringify(this.savedTabs);
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
		return steps.map((step) => {
			if (!Array.isArray(step.depends_on)) {
				throw new Error(`Step ${step.id} missing depends_on`);
			}
			if (typeof step.is_applied !== 'boolean') {
				throw new Error(`Step ${step.id} missing is_applied`);
			}
			return {
				...step,
				type: normalizeStepType(step.type),
				config: normalizeConfig(step.type, step.config as Record<string, unknown>) as Record<
					string,
					unknown
				>,
				depends_on: step.depends_on,
				is_applied: step.is_applied
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

	duplicateTab(tabId: string): AnalysisTab | null {
		const sourceIndex = this.tabs.findIndex((tab) => tab.id === tabId);
		if (sourceIndex < 0) return null;
		const sourceTab = this.tabs[sourceIndex];
		if (!sourceTab) return null;

		const nextName = nextDuplicateTabName(this.tabs, sourceTab.name);
		const nextTabId = `tab-${uuid()}`;
		const nextOutputId = uuid();
		const nextFilename = slugifyOutputName(nextName);
		const sourceOutput = cloneJson(sourceTab.output);
		const sourceIceberg = sourceOutput.iceberg;

		const stepIdMap: Record<string, string> = {};
		for (const step of sourceTab.steps) {
			stepIdMap[step.id] = uuid();
		}

		const duplicatedSteps: PipelineStep[] = [];
		for (const step of sourceTab.steps) {
			const mappedStepId = stepIdMap[step.id];
			if (!mappedStepId) return null;
			const dependsOn: string[] = [];
			for (const depId of step.depends_on ?? []) {
				const mappedDepId = stepIdMap[depId];
				if (!mappedDepId) return null;
				dependsOn.push(mappedDepId);
			}
			duplicatedSteps.push({
				...step,
				id: mappedStepId,
				config: cloneJson(step.config),
				depends_on: dependsOn
			});
		}

		const duplicatedOutput = {
			...sourceOutput,
			result_id: nextOutputId,
			filename: nextFilename
		};
		if (isRecord(sourceIceberg)) {
			duplicatedOutput.iceberg = {
				...sourceIceberg,
				table_name: nextFilename
			};
		}

		const duplicatedTab: AnalysisTab = {
			...sourceTab,
			id: nextTabId,
			name: nextName,
			datasource: {
				...sourceTab.datasource,
				config: cloneJson(sourceTab.datasource.config)
			},
			output: duplicatedOutput,
			steps: duplicatedSteps
		};

		const nextTabs = [...this.tabs];
		nextTabs.splice(sourceIndex + 1, 0, duplicatedTab);
		this.tabs = nextTabs;
		this.activeTabId = duplicatedTab.id;
		return duplicatedTab;
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
		const isChart = isChartStep(step.type);

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
		const snapshotId =
			(configSnapshot.time_travel_snapshot_id as string | null | undefined) ?? null;
		const snapshotMs =
			(configSnapshot.time_travel_snapshot_timestamp_ms as number | null | undefined) ?? null;
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
			const depSnapshotId =
				(depConfig.time_travel_snapshot_id as string | null | undefined) ?? null;
			const depSnapshotMs =
				(depConfig.time_travel_snapshot_timestamp_ms as number | null | undefined) ?? null;
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
		const isChart = isChartStep(movingStep.type);

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
			return errAsync({
				type: 'parse' as const,
				message: 'No analysis loaded'
			});
		}

		this.loading = true;
		this.error = null;

		const errors = validatePipelineTabs(this.tabs);
		if (errors.length) {
			this.loading = false;
			return errAsync({
				type: 'parse' as const,
				message: errors[0]?.message ?? 'Pipeline validation failed'
			});
		}
		const update: AnalysisUpdate = {
			name: this.current.name,
			description: this.current.description,
			tabs: this.tabs
		};

		const version = this.current.version ?? null;

		return updateAnalysis(this.current.id, update, version)
			.andThen(({ analysis: updated, version: nextVersion }) => {
				this.current = { ...updated, version: nextVersion };
				this.lastSaved = { name: updated.name, description: updated.description ?? null };
				const tabs = (updated.pipeline_definition as { tabs?: AnalysisTab[] })?.tabs ?? [];
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

	update(updates: { name?: string; description?: string | null }): void {
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
				output: buildOutputConfig({
					outputId: uuid(),
					name: generateOutputName(),
					branch: 'master'
				}),
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
