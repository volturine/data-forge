import type { Analysis, AnalysisTab, AnalysisUpdate, PipelineStep } from '$lib/types/analysis';
import type { SchemaInfo } from '$lib/types/datasource';
import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
import type { Schema } from '$lib/types/schema';
import { getAnalysisWithHeaders, updateAnalysis } from '$lib/api/analysis';
import { normalizeDtype } from '$lib/utils/transform';
import { normalizeConfig } from '$lib/utils/step-config-defaults';
import { track } from '$lib/utils/audit-log';
import { schemaStore } from '$lib/stores/schema.svelte';
import { getLockPayload } from '$lib/stores/lockManager.svelte';
import { SvelteMap } from 'svelte/reactivity';
import { ResultAsync, err, ok } from 'neverthrow';
import type { ApiError } from '$lib/api/client';
import { idbGet, idbSet } from '$lib/utils/indexeddb';

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

	activeTab = $derived.by(() => {
		const match = this.tabs.find((tab) => tab.id === this.activeTabId) ?? null;
		if (match) return match;
		return this.tabs[0] ?? null;
	});

	// Current tab's pipeline
	pipeline = $derived.by(() => {
		return this.activeTab?.steps ?? [];
	});

	calculatedSchema = $derived.by(() => {
		const steps = this.pipeline;
		if (!steps.length || !this.sourceSchemas.size) return null;

		// Use the active tab's datasource schema
		const datasourceId = this.activeTab?.datasource_id;
		const sourceSchema = datasourceId
			? this.sourceSchemas.get(datasourceId)
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

		const definition = analysis.pipeline_definition as {
			steps?: PipelineStep[];
			tabs?: AnalysisTab[];
			datasource_ids?: string[];
		};

		const tabs = analysis.tabs?.length ? analysis.tabs : definition?.tabs;
		if (tabs && tabs.length && tabs[0].steps !== undefined) {
			const normalized = this.normalizeTabSteps(tabs);
			this.setTabs(normalized);
			this.savedTabs = normalized;
			this.loading = false;
			this.error = null;
			return;
		}

		const legacySteps = definition?.steps ?? [];

		if (tabs && tabs.length) {
			const migratedTabs = tabs.map((tab, index) => ({
				...tab,
				steps: index === 0 ? legacySteps : []
			}));
			const normalized = this.normalizeTabSteps(migratedTabs);
			this.setTabs(normalized);
			this.savedTabs = normalized;
			this.loading = false;
			this.error = null;
			return;
		}

		const defaults = this.buildTabs(definition?.datasource_ids ?? [], legacySteps);
		const normalized = this.normalizeTabSteps(defaults);
		this.setTabs(normalized);
		this.savedTabs = normalized;
		this.loading = false;
		this.error = null;
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

				const definition = analysis.pipeline_definition as {
					steps?: PipelineStep[];
					tabs?: AnalysisTab[];
					datasource_ids?: string[];
				};

				const tabs = analysis.tabs?.length ? analysis.tabs : definition?.tabs;
				if (tabs && tabs.length && tabs[0].steps !== undefined) {
					const normalized = this.normalizeTabSteps(tabs);
					this.setTabs(normalized);
					this.savedTabs = normalized;
					this.loading = false;
					return ok(undefined);
				}

				const legacySteps = definition?.steps ?? [];

				if (tabs && tabs.length) {
					const migratedTabs = tabs.map((tab, index) => ({
						...tab,
						steps: index === 0 ? legacySteps : []
					}));
					const normalized = this.normalizeTabSteps(migratedTabs);
					this.setTabs(normalized);
					this.savedTabs = normalized;
					this.loading = false;
					return ok(undefined);
				}

				const defaults = this.buildTabs(definition?.datasource_ids ?? [], legacySteps);
				const normalized = this.normalizeTabSteps(defaults);
				this.setTabs(normalized);
				this.savedTabs = normalized;
				this.loading = false;
				return ok(undefined);
			})
			.mapErr((error) => {
				if (this.loadId !== token) return error;
				this.error = error.message;
				this.loading = false;
				return error;
			});
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
			if (currentTab.type !== savedTab.type) return true;
			if ((currentTab.parent_id ?? null) !== (savedTab.parent_id ?? null)) return true;
			if ((currentTab.datasource_id ?? null) !== (savedTab.datasource_id ?? null)) return true;
			const currentConfig = JSON.stringify(currentTab.datasource_config ?? {});
			const savedConfig = JSON.stringify(savedTab.datasource_config ?? {});
			if (currentConfig !== savedConfig) return true;
			const currentSteps = currentTab.steps ?? [];
			const savedSteps = savedTab.steps ?? [];
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
				for (let k = 0; k < currentDepends.length; k += 1) {
					if (currentDepends[k] !== savedDepends[k]) return true;
				}
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
		const analysisId = this.current ? this.current.id : null;
		track({
			event: 'analysis_step',
			action,
			target: step.type,
			meta: {
				analysis_id: analysisId,
				tab_id: this.activeTabId,
				step_id: step.id,
				...meta
			}
		});
	}

	addStep(step: PipelineStep): void {
		if (!this.activeTab) return;
		const steps = this.activeTab.steps;
		const parentId = steps.length ? (steps[steps.length - 1]?.id ?? null) : null;
		step.depends_on = parentId ? [parentId] : [];
		const newSteps = [...steps, step].map((item) => ({
			...item,
			config: JSON.parse(JSON.stringify(item.config)) as Record<string, unknown>
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

	private normalizeTabSteps(tabs: AnalysisTab[]): AnalysisTab[] {
		return tabs.map((tab) => ({
			...tab,
			steps: this.normalizeSteps(tab.steps)
		}));
	}

	private normalizeSteps(steps: PipelineStep[]): PipelineStep[] {
		if (!steps.length) return steps;
		const hasDependencies = steps.some((step) => (step.depends_on ?? []).length > 0);

		const normalized = steps.map((step, index) => {
			const isApplied = step.is_applied !== false;
			const normalizedType = step.type.startsWith('plot_') ? 'chart' : step.type;
			// Normalize config to ensure proper shape (handles backward compatibility)
			const normalizedConfig = normalizeConfig(step.type, step.config as Record<string, unknown>);

			if (!hasDependencies) {
				// Legacy: add dependencies based on position
				if (index === 0) {
					return {
						...step,
						type: normalizedType,
						config: normalizedConfig as Record<string, unknown>,
						depends_on: [],
						is_applied: isApplied
					};
				}
				const parentId = steps[index - 1]?.id ?? null;
				return {
					...step,
					type: normalizedType,
					config: normalizedConfig as Record<string, unknown>,
					depends_on: parentId ? [parentId] : [],
					is_applied: isApplied
				};
			}

			return {
				...step,
				type: normalizedType,
				config: normalizedConfig as Record<string, unknown>,
				is_applied: isApplied
			};
		});

		return normalized;
	}

	setActiveTab(id: string): void {
		this.activeTabId = id;
	}

	addTab(tab: AnalysisTab): void {
		// Ensure new tabs have empty steps array
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
		const normalizedParentId = parentId ?? null;
		step.depends_on = normalizedParentId ? [normalizedParentId] : [];
		const isChart = step.type === 'chart' || step.type.startsWith('plot_');

		if (nextId) {
			const nextStepIndex = nextPipeline.findIndex((item) => item.id === nextId);
			if (nextStepIndex < 0) {
				return false;
			}
			if (isChart) {
				// Charts are pass-through — do not rewire dependencies.
				// The chart simply observes data at this point; downstream
				// steps keep their existing parent link.
			} else {
				const nextStep = nextPipeline[nextStepIndex];
				const nextDeps = nextStep.depends_on ?? [];
				if (nextDeps.length > 1) {
					return false;
				}
				if (normalizedParentId && nextDeps.length > 0 && nextDeps[0] !== normalizedParentId) {
					return false;
				}
				if (!normalizedParentId && nextDeps.length > 0) {
					return false;
				}
				nextPipeline[nextStepIndex] = { ...nextStep, depends_on: [step.id] };
			}
		}

		nextPipeline.splice(index, 0, step);
		const nextSteps = nextPipeline.map((item) => ({
			...item,
			config: JSON.parse(JSON.stringify(item.config)) as Record<string, unknown>
		}));
		this.updateTabSteps(this.activeTab.id, nextSteps);
		this.logStep('insert', step, { index });
		return true;
	}

	addBranchStep(step: PipelineStep, parentId: string | null): void {
		if (!this.activeTab) return;
		step.depends_on = parentId ? [parentId] : [];
		const newSteps = [...this.activeTab.steps, step].map((item) => ({
			...item,
			config: JSON.parse(JSON.stringify(item.config)) as Record<string, unknown>
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
						config: JSON.parse(
							JSON.stringify((updates.config ?? step.config) as Record<string, unknown>)
						) as Record<string, unknown>
					}
				: step
		);
		this.updateTabSteps(this.activeTab.id, nextPipeline);
	}

	updateStepConfig(id: string, config: Record<string, unknown>): void {
		if (!this.activeTab) return;
		const safeConfig = JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
		const nextPipeline = this.activeTab.steps.map((step) =>
			step.id === id ? { ...step, config: safeConfig } : step
		);
		this.updateTabSteps(this.activeTab.id, nextPipeline);
		const step = nextPipeline.find((item) => item.id === id);
		if (!step) return;
		const keys = Object.keys(safeConfig);
		this.logStep('update', step, { keys, count: keys.length });
		const analysisId = this.current?.id ?? null;
		const datasourceId = this.activeTab.datasource_id ?? null;
		if (!analysisId || !datasourceId) return;
		const configSnapshot = (this.activeTab.datasource_config ?? {}) as Record<string, unknown>;
		const snapshotId = (configSnapshot.snapshot_id as string | null | undefined) ?? null;
		const snapshotMs = (configSnapshot.snapshot_timestamp_ms as number | null | undefined) ?? null;
		const snapshotKey = `${snapshotId ?? 'latest'}:${snapshotMs ?? 0}`;
		const edges: Record<string, string[]> = {};
		for (const item of nextPipeline) {
			const deps = item.depends_on ?? [];
			for (const dep of deps) {
				const next = edges[dep] ?? [];
				next.push(item.id);
				edges[dep] = next;
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
			const cfg = (tab.datasource_config ?? {}) as Record<string, unknown>;
			if (String(cfg.analysis_tab_id ?? '') !== activeTabId) continue;
			if (String(cfg.analysis_id ?? '') !== analysisId) continue;
			const depDatasourceId = tab.datasource_id ?? null;
			if (!depDatasourceId) continue;
			const depConfig = (tab.datasource_config ?? {}) as Record<string, unknown>;
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

		// Find the parent of the removed step
		const removedDeps = removedStep.depends_on ?? [];
		const removedParentId = removedDeps[0] ?? null;

		// Update steps that depended on the removed step to now depend on its parent
		const nextPipeline = steps
			.filter((step) => step.id !== id)
			.map((step) => {
				const deps = step.depends_on ?? [];
				if (deps.includes(id)) {
					// This step depended on the removed step, update to point to removed step's parent
					return {
						...step,
						depends_on: removedParentId ? [removedParentId] : []
					};
				}
				return step;
			});

		// Get all affected step IDs (the removed step and all its descendants)
		const affectedIds = [id];
		for (const step of steps) {
			if (step.depends_on?.includes(id)) {
				affectedIds.push(step.id);
			}
		}

		this.updateTabSteps(this.activeTab.id, nextPipeline);
		this.logStep('remove', removedStep, { parent_id: removedParentId });
		// No cache invalidation needed - SchemaStore uses $derived
	}

	reorderSteps(fromIndex: number, toIndex: number): void {
		if (!this.activeTab) return;
		const steps = [...this.activeTab.steps];
		const [moved] = steps.splice(fromIndex, 1);
		const movedCopy = {
			...moved,
			config: JSON.parse(JSON.stringify(moved.config))
		};
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

		const pipelineSteps = this.tabs.flatMap((tab) => tab.steps ?? []);
		const update: AnalysisUpdate = {
			name: this.current.name,
			description: this.current.description,
			tabs: this.tabs,
			pipeline_steps: pipelineSteps,
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
					const normalized = this.normalizeTabSteps(tabs);
					this.tabs = normalized;
					this.savedTabs = normalized;
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

	buildTabs(datasourceIds: string[], initialSteps: PipelineStep[] = []): AnalysisTab[] {
		return datasourceIds.map((datasourceId, index) => ({
			id: `tab-${datasourceId}`,
			name: `Source ${index + 1}`,
			type: 'datasource' as const,
			parent_id: null,
			datasource_id: datasourceId,
			steps: index === 0 ? initialSteps : []
		}));
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
