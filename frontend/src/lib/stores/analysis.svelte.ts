import type { Analysis, AnalysisTab, AnalysisUpdate, PipelineStep } from '$lib/types/analysis';
import type { SchemaInfo } from '$lib/types/datasource';
import type { Schema } from '$lib/types/schema';
import { getAnalysis, updateAnalysis } from '$lib/api/analysis';
import { schemaCalculator } from '$lib/utils/schema';

export class AnalysisStore {
	current = $state<Analysis | null>(null);
	pipeline = $state<PipelineStep[]>([]);
	tabs = $state<AnalysisTab[]>([]);
	activeTabId = $state<string | null>(null);
	sourceSchemas = $state(new Map<string, SchemaInfo>());
	loading = $state(false);
	error = $state<string | null>(null);

	activeTab = $derived.by(() => {
		const match = this.tabs.find((tab) => tab.id === this.activeTabId) ?? null;
		if (match) return match;
		return this.tabs[0] ?? null;
	});

	calculatedSchema = $derived.by(() => {
		if (!this.pipeline.length || !this.sourceSchemas.size) return null;
		const sourceSchema = this.sourceSchemas.values().next().value;
		if (!sourceSchema) return null;

		// Convert SchemaInfo to Schema (both have same structure)
		const baseSchema: Schema = {
			columns: sourceSchema.columns.map((col) => ({
				name: col.name,
				dtype: col.dtype,
				nullable: col.nullable
			})),
			row_count: sourceSchema.row_count
		};

		return schemaCalculator.calculatePipelineSchema(baseSchema, this.pipeline);
	});

	async loadAnalysis(id: string): Promise<void> {
		this.loading = true;
		this.error = null;

		try {
			const analysis = await getAnalysis(id);
			this.current = analysis;

			const definition = analysis.pipeline_definition as {
				steps?: PipelineStep[];
				tabs?: AnalysisTab[];
				datasource_ids?: string[];
			};

			const steps = definition?.steps ?? [];
			this.pipeline = steps;

					const tabs = analysis.tabs?.length ? analysis.tabs : definition?.tabs;
			if (tabs && tabs.length) {
				this.setTabs(tabs);
				return;
			}

			const defaults = this.buildTabs(definition?.datasource_ids ?? []);
			this.setTabs(defaults);
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to load analysis';
			throw err;
		} finally {
			this.loading = false;
		}
	}

	addStep(step: PipelineStep): void {
		this.pipeline = [...this.pipeline, step];
		schemaCalculator.invalidateCache(this.pipeline, [step.id]);
	}

	setTabs(tabs: AnalysisTab[]): void {
		this.tabs = tabs;
		if (this.activeTabId && tabs.some((tab) => tab.id === this.activeTabId)) {
			return;
		}
		this.activeTabId = tabs[0]?.id ?? null;
	}

	setActiveTab(id: string): void {
		this.activeTabId = id;
	}

	addTab(tab: AnalysisTab): void {
		this.tabs = [...this.tabs, tab];
		this.activeTabId = tab.id;
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

	insertStep(
		step: PipelineStep,
		index: number,
		parentId: string | null,
		nextId: string | null
	): boolean {
		const nextPipeline = [...this.pipeline];
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
			nextStep.depends_on = [step.id];
		}

		nextPipeline.splice(index, 0, step);
		this.pipeline = nextPipeline;
		const invalidated = nextId ? [step.id, nextId] : [step.id];
		schemaCalculator.invalidateCache(nextPipeline, invalidated);
		return true;
	}

	addBranchStep(step: PipelineStep, parentId: string | null): void {
		step.depends_on = parentId ? [parentId] : [];
		this.pipeline = [...this.pipeline, step];
		schemaCalculator.invalidateCache(this.pipeline, [step.id]);
	}

	updateStep(id: string, updates: Partial<PipelineStep>): void {
		const nextPipeline = this.pipeline.map((step) => (step.id === id ? { ...step, ...updates } : step));
		this.pipeline = nextPipeline;
		schemaCalculator.invalidateCache(nextPipeline, [id]);
	}

	removeStep(id: string): void {
		this.pipeline = this.pipeline.filter((step) => step.id !== id);
		schemaCalculator.invalidateCache(this.pipeline, [id]);
	}

	reorderSteps(fromIndex: number, toIndex: number): void {
		const steps = [...this.pipeline];
		const [moved] = steps.splice(fromIndex, 1);
		steps.splice(toIndex, 0, moved);
		this.pipeline = steps;
	}

	/**
	 * Move an existing step to a new position in the pipeline.
	 * Updates dependency chains accordingly.
	 */
	moveStep(stepId: string, toIndex: number, newParentId: string | null, newNextId: string | null): boolean {
		const steps = [...this.pipeline];
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

		this.pipeline = steps;
		schemaCalculator.invalidateCache(steps, [stepId]);
		return true;
	}

	async save(): Promise<void> {
		if (!this.current) {
			throw new Error('No analysis loaded');
		}

		this.loading = true;
		this.error = null;

		try {
			const update: AnalysisUpdate = {
				pipeline_steps: this.pipeline,
				tabs: this.tabs
			};

			const updated = await updateAnalysis(this.current.id, update);
			this.current = updated;
			const tabs = updated.tabs ?? [];
			if (tabs.length) {
				this.tabs = tabs;
				// Preserve activeTabId if it still exists, otherwise fall back to first tab
				if (!this.activeTabId || !tabs.some((tab) => tab.id === this.activeTabId)) {
					this.activeTabId = this.tabs[0]?.id ?? null;
				}
			}
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to save analysis';
			throw err;
		} finally {
			this.loading = false;
		}
	}

	setSourceSchema(datasourceId: string, schema: SchemaInfo): void {
		this.sourceSchemas.set(datasourceId, schema);
		// Trigger reactivity by creating new Map
		this.sourceSchemas = new Map(this.sourceSchemas);
	}

	clearSourceSchemas(): void {
		this.sourceSchemas.clear();
		this.sourceSchemas = new Map();
	}

	reset(): void {
		this.current = null;
		this.pipeline = [];
		this.tabs = [];
		this.activeTabId = null;
		this.sourceSchemas.clear();
		this.sourceSchemas = new Map();
		this.error = null;
		this.loading = false;
	}

	buildTabs(datasourceIds: string[]): AnalysisTab[] {
		return datasourceIds.map((datasourceId, index) => ({
			id: `tab-${datasourceId}`,
			name: `Source ${index + 1}`,
			type: 'datasource',
			parent_id: null,
			datasource_id: datasourceId
		}));
	}
}

export type AnalysisStoreApi = {
	insertStep: (step: PipelineStep, index: number, parentId: string | null, nextId: string | null) => boolean;
	addBranchStep: (step: PipelineStep, parentId: string | null) => void;
};

export const analysisStore = new AnalysisStore();
