import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { emptySchema } from '$lib/types/schema';
import { getStepTransform, joinTransform, type StepConfig } from '$lib/utils/transform';
import { SvelteMap } from 'svelte/reactivity';

export interface StepSchemas {
	input: Schema;
	output: Schema;
}

class SchemaStore {
	joinSchemas = $state(new SvelteMap<string, Schema>());

	get primaryDatasourceId(): string | null {
		const activeTab = analysisStore.activeTab;
		return activeTab?.datasource_id ?? null;
	}

	get steps(): PipelineStep[] {
		return analysisStore.pipeline;
	}

	async setJoinDatasource(datasourceId: string, schema: Schema): Promise<void> {
		this.joinSchemas.set(datasourceId, schema);
	}

	removeJoinDatasource(datasourceId: string): void {
		this.joinSchemas.delete(datasourceId);
	}

	getJoinSchema(datasourceId: string): Schema | null {
		return this.joinSchemas.get(datasourceId) ?? null;
	}

	getJoinSchemaByStepId(stepId: string): Schema | null {
		return this.joinSchemas.get(stepId) ?? null;
	}

	getStepSchemas(): Map<string, StepSchemas> {
		const schemas = new SvelteMap<string, StepSchemas>();
		let currentSchema: Schema | null = null;

		const activeTab = analysisStore.activeTab;
		const sourceSchema = activeTab?.datasource_id
			? (analysisStore.sourceSchemas.get(activeTab.datasource_id) ?? null)
			: null;

		for (const step of this.steps) {
			const input =
				currentSchema ??
				(sourceSchema ? { columns: sourceSchema.columns, row_count: null } : emptySchema());
			const config = step.config as StepConfig;
			const transformer = getStepTransform(step);

			let output: Schema;

			if (step.type === 'join') {
				const rightSchema = this.joinSchemas.get(step.id) ?? emptySchema();
				const config = step.config as StepConfig;
				output = joinTransform(input, config, rightSchema);
			} else {
				output = transformer(input, config);
			}

			schemas.set(step.id, { input, output });
			currentSchema = output;
		}

		return schemas;
	}

	getInput(stepId: string): Schema | null {
		return this.getStepSchemas().get(stepId)?.input ?? null;
	}

	getOutput(stepId: string): Schema | null {
		return this.getStepSchemas().get(stepId)?.output ?? null;
	}

	getAllOutputs(): Schema[] {
		const result: Schema[] = [];
		for (const step of this.steps) {
			const output = this.getOutput(step.id);
			if (output) result.push(output);
		}
		return result;
	}

	getLastOutput(): Schema | null {
		if (this.steps.length === 0) return null;
		return this.getOutput(this.steps[this.steps.length - 1].id);
	}

	reset(): void {
		this.joinSchemas = new SvelteMap();
	}
}

export const schemaStore = new SchemaStore();
