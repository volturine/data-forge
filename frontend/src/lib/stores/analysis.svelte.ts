import type { Analysis, AnalysisUpdate, PipelineStep } from '$lib/types/analysis';
import type { SchemaInfo } from '$lib/types/datasource';
import type { Schema } from '$lib/types/schema';
import { getAnalysis, updateAnalysis } from '$lib/api/analysis';
import { schemaCalculator } from '$lib/utils/schema';

class AnalysisStore {
	current = $state<Analysis | null>(null);
	pipeline = $state<PipelineStep[]>([]);
	sourceSchemas = $state(new Map<string, SchemaInfo>());
	loading = $state(false);
	error = $state<string | null>(null);

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

			// Extract pipeline steps from pipeline_definition
			if (analysis.pipeline_definition && 'steps' in analysis.pipeline_definition) {
				this.pipeline = analysis.pipeline_definition.steps as PipelineStep[];
			} else {
				this.pipeline = [];
			}
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to load analysis';
			throw err;
		} finally {
			this.loading = false;
		}
	}

	addStep(step: PipelineStep): void {
		this.pipeline = [...this.pipeline, step];
	}

	updateStep(id: string, updates: Partial<PipelineStep>): void {
		this.pipeline = this.pipeline.map((step) => (step.id === id ? { ...step, ...updates } : step));
	}

	removeStep(id: string): void {
		this.pipeline = this.pipeline.filter((step) => step.id !== id);
	}

	reorderSteps(fromIndex: number, toIndex: number): void {
		const steps = [...this.pipeline];
		const [moved] = steps.splice(fromIndex, 1);
		steps.splice(toIndex, 0, moved);
		this.pipeline = steps;
	}

	async save(): Promise<void> {
		if (!this.current) {
			throw new Error('No analysis loaded');
		}

		this.loading = true;
		this.error = null;

		try {
			const update: AnalysisUpdate = {
				pipeline_steps: this.pipeline
			};

			const updated = await updateAnalysis(this.current.id, update);
			this.current = updated;
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
		this.sourceSchemas.clear();
		this.sourceSchemas = new Map();
		this.error = null;
		this.loading = false;
	}
}

export const analysisStore = new AnalysisStore();
