import type { Analysis, AnalysisTab, AnalysisUpdate, PipelineStep } from '#lib/types/analysis.js';

import type { SchemaInfo } from '#lib/types/datasource.js';
import type { ComputeWorkerResourceConfig } from '#lib/types/compute.js';
import { getAnalysisWithHeaders, updateAnalysis, type AnalysisDetail } from '#lib/api/analysis.js';
import { ensureTabDefaults, validatePipelineTabs } from '#lib/utils/analysis-tab.js';
import { normalizeConfig } from '#lib/utils/step-config-defaults.js';
import { isChartStep, normalizeStepType } from '#lib/components/pipeline/utils.js';
import { track } from '#lib/utils/audit-log.js';
import { cloneJson } from '#lib/utils/json.js';
import { uuid } from '#lib/utils/uuid.js';
import { SvelteMap } from 'svelte/reactivity';
import { ResultAsync, errAsync, ok } from 'neverthrow';
import type { ApiError } from '#lib/api/client.js';
import { PreviewState } from '#lib/editor/preview-state.svelte.js';

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

export class AnalysisStore {
	current = $state<Analysis | null>(null);
	tabs = $state<AnalysisTab[]>([]);
	savedTabs = $state<AnalysisTab[]>([]);
	activeTabId = $state<string | null>(null);
	sourceSchemas = $state(new SvelteMap<string, SchemaInfo>());
	resourceConfig = $state<ComputeWorkerResourceConfig | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	private loadId = 0;
	lastSaved = $state<{ name: string; description: string | null } | null>(null);
	readonly previews = new PreviewState();
	currentRevision = $state<string | null>(null);

	activeTab: AnalysisTab | null = $derived(
		this.tabs.find((tab) => tab.id === this.activeTabId) ?? this.tabs[0] ?? null
	);

	activeSchemaKey = $derived.by(() => {
		const tab = this.activeTab;
		const analysisId = this.current?.id ?? null;
		if (!tab || !analysisId) return null;
		const sourceTabId = tab.datasource.analysis_tab_id;
		if (sourceTabId) {
			return `output:${analysisId}:${sourceTabId}`;
		}
		return tab.datasource.id;
	});

	pipeline = $derived(this.activeTab?.steps ?? []);

	applyAnalysis(analysis: Analysis): void {
		const previousId = this.current?.id ?? null;
		if (previousId !== analysis.id) {
			this.activeTabId = null;
			this.sourceSchemas.clear();
		}
		this.applyDetail(analysis, String(analysis.revision));
	}

	loadAnalysis(id: string): ResultAsync<void, ApiError> {
		const token = this.loadId + 1;
		this.loadId = token;
		this.reset();
		this.loading = true;
		this.error = null;

		return getAnalysisWithHeaders(id)
			.andThen((result) => {
				if ('notModified' in result) return ok(undefined);
				if (this.loadId !== token) return ok(undefined);
				this.applyDetail(result.analysis, result.version);
				return ok(undefined);
			})
			.mapErr((error) => {
				if (this.loadId !== token) return error;
				this.error = error.message;
				this.loading = false;
				return error;
			});
	}

	private applyDetail(analysis: Analysis, revision: string): void {
		this.current = analysis;
		this.currentRevision = revision;
		this.lastSaved = { name: analysis.name, description: analysis.description };
		this.resolveTabs(analysis);
	}

	private resolveTabs(analysis: Analysis): void {
		const tabs = (analysis.pipeline_definition as { tabs?: AnalysisTab[] })?.tabs;
		if (tabs?.length) {
			this.applyTabs(tabs);
			return;
		}
		this.applyTabs([]);
	}

	isDirty(): boolean {
		if (!this.current) return false;
		const saved = this.lastSaved ?? {
			name: this.current.name,
			description: this.current.description
		};
		if (this.current.name !== saved.name || this.current.description !== saved.description)
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
			config: cloneJson(item.config)
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
		this.savedTabs = cloneJson(sanitized);
		this.loading = false;
		this.error = null;
	}

	restoreSavedSnapshot(): boolean {
		if (!this.current || !this.lastSaved) return false;

		const activeTabId = this.activeTabId;
		this.current = {
			...this.current,
			name: this.lastSaved.name,
			description: this.lastSaved.description
		};
		this.tabs = cloneJson(this.savedTabs);
		this.activeTabId =
			activeTabId && this.tabs.some((tab) => tab.id === activeTabId)
				? activeTabId
				: (this.tabs[0]?.id ?? null);
		this.loading = false;
		this.error = null;
		return true;
	}

	private normalizeTabSteps(tabs: AnalysisTab[]): AnalysisTab[] {
		return tabs.map((tab) => ({
			...tab,
			datasource: { ...tab.datasource, config: { ...tab.datasource.config } },
			steps: this.normalizeSteps(tab.steps)
		}));
	}

	private normalizeSteps(steps: PipelineStep[]): PipelineStep[] {
		// Coerce missing fields instead of throwing — a hard throw during load or
		// draft restore surfaces as SvelteKit's generic 500 page and blanks the editor.
		return steps.map((step, index) => {
			const depends_on = Array.isArray(step.depends_on)
				? step.depends_on
				: index > 0
					? [steps[index - 1].id]
					: [];
			const is_applied = typeof step.is_applied === 'boolean' ? step.is_applied : true;
			return {
				...step,
				type: normalizeStepType(step.type),
				config: normalizeConfig(step.type, step.config as Record<string, unknown>) as Record<
					string,
					unknown
				>,
				depends_on,
				is_applied
			};
		});
	}

	setActiveTab(id: string): void {
		this.activeTabId = id;
	}

	addTab(tab: AnalysisTab): void {
		this.tabs = [...this.tabs, tab];
		this.activeTabId = tab.id;
	}

	duplicateTab(tabId: string): AnalysisTab | null {
		const sourceIndex = this.tabs.findIndex((tab) => tab.id === tabId);
		if (sourceIndex < 0) return null;
		const sourceTab = this.tabs[sourceIndex];

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
			const dependsOn: string[] = [];
			for (const depId of step.depends_on ?? []) {
				const mappedDepId = stepIdMap[depId];
				if (!mappedDepId) return null;
				dependsOn.push(mappedDepId);
			}
			duplicatedSteps.push({
				...step,
				id: stepIdMap[step.id],
				config: cloneJson(step.config),
				depends_on: dependsOn
			});
		}

		const duplicatedOutput = {
			...sourceOutput,
			result_id: nextOutputId,
			filename: nextFilename
		};
		if (sourceIceberg) {
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
		const nextSteps = nextPipeline.map((item) => ({ ...item, config: cloneJson(item.config) }));
		this.updateTabSteps(this.activeTab.id, nextSteps);
		this.logStep('insert', step, { index });
		return true;
	}

	updateStep(id: string, updates: Partial<PipelineStep>): void {
		if (!this.activeTab) return;
		const nextPipeline = this.activeTab.steps.map((step) =>
			step.id === id
				? {
						...step,
						...updates,
						config: cloneJson(updates.config ?? step.config)
					}
				: step
		);
		this.updateTabSteps(this.activeTab.id, nextPipeline);
	}

	updateStepConfig(id: string, config: Record<string, unknown>): void {
		if (!this.activeTab) return;
		const safeConfig = cloneJson(config);
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

	save(): ResultAsync<AnalysisDetail, ApiError> {
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
				message: errors[0].message
			});
		}
		const update: AnalysisUpdate = {
			name: this.current.name,
			description: this.current.description,
			tabs: this.tabs
		};

		const version = this.currentRevision;
		if (version === null) {
			this.loading = false;
			return errAsync({
				type: 'parse' as const,
				message: 'Analysis response is missing its revision'
			});
		}

		return updateAnalysis(this.current.id, update, version)
			.andThen(({ analysis: updated, etag, version: nextVersion }) => {
				this.applyDetail(updated, nextVersion);
				return ok({ analysis: updated, etag, version: nextVersion });
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

	setResourceConfig(config: ComputeWorkerResourceConfig | null): void {
		this.resourceConfig = config;
	}

	reset(): void {
		this.current = null;
		this.currentRevision = null;
		this.tabs = [];
		this.savedTabs = [];
		this.activeTabId = null;
		this.sourceSchemas.clear();
		this.resourceConfig = null;
		this.lastSaved = null;
		this.loading = false;
		this.error = null;
		this.previews.paused = false;
	}
}

export const analysisStore = new AnalysisStore();
