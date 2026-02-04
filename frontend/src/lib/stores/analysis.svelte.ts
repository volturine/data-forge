import type { Analysis, AnalysisTab, AnalysisUpdate, PipelineStep } from '$lib/types/analysis';
import type { SchemaInfo } from '$lib/types/datasource';
import type { EngineResourceConfig, EngineDefaults } from '$lib/types/compute';
import type { Schema } from '$lib/types/schema';
import { getAnalysis, updateAnalysis } from '$lib/api/analysis';
import { normalizeDtype } from '$lib/utils/transform';
import { normalizeConfig } from '$lib/utils/step-config-defaults';
import { track } from '$lib/utils/audit-log';
import { schemaStore } from '$lib/stores/schema.svelte';
import { SvelteMap } from 'svelte/reactivity';
import { ResultAsync, err, ok } from 'neverthrow';
import type { ApiError } from '$lib/api/client';

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

	loadAnalysis(id: string): ResultAsync<void, ApiError> {
		this.loading = true;
		this.error = null;

		return getAnalysis(id)
			.andThen((analysis) => {
				this.current = analysis;

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
				this.error = error.message;
				this.loading = false;
				return error;
			});
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
			// Normalize config to ensure proper shape (handles backward compatibility)
			const normalizedConfig = normalizeConfig(step.type, step.config as Record<string, unknown>);

			if (!hasDependencies) {
				// Legacy: add dependencies based on position
				if (index === 0) {
					return {
						...step,
						config: normalizedConfig as Record<string, unknown>,
						depends_on: [],
						is_applied: isApplied
					};
				}
				const parentId = steps[index - 1]?.id ?? null;
				return {
					...step,
					config: normalizedConfig as Record<string, unknown>,
					depends_on: parentId ? [parentId] : [],
					is_applied: isApplied
				};
			}

			return {
				...step,
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

		if (nextId) {
			const nextStepIndex = nextPipeline.findIndex((item) => item.id === nextId);
			if (nextStepIndex < 0) {
				return false;
			}
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
		steps.splice(toIndex, 0, moved);
		this.updateTabSteps(this.activeTab.id, steps);
		this.logStep('reorder', moved, { from: fromIndex, to: toIndex });
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

		// Find the step that depended on the moving step (if any)
		const dependentStep = steps.find((s) => s.depends_on?.includes(stepId));

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
		if (newNextId) {
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

		const pipelineSteps = this.tabs.flatMap((tab) => tab.steps ?? []);
		const update: AnalysisUpdate = {
			name: this.current.name,
			description: this.current.description,
			tabs: this.tabs,
			pipeline_steps: pipelineSteps
		};

		return updateAnalysis(this.current.id, update)
			.andThen((updated) => {
				this.current = updated;
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
