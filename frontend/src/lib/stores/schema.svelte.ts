import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import type { SchemaInfo } from '$lib/types/datasource';
import { datasourceStore } from '$lib/stores/datasource.svelte';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { getStepTransform, type StepConfig } from '$lib/utils/schema/ops';
import { emptySchema } from '$lib/types/schema';
import { joinTransform } from '$lib/utils/schema/ops';

export interface StepSchemas {
	input: Schema;
	output: Schema;
}

class SchemaStore {
	joinSchemas = $state<Map<string, Schema>>(new Map());

	get primaryDatasourceId(): string | null {
		const activeTab = analysisStore.activeTab;
		return activeTab?.datasource_id ?? null;
	}

	get steps(): PipelineStep[] {
		return analysisStore.pipeline;
	}

	async setJoinDatasource(datasourceId: string, schema: Schema): Promise<void> {
		const next = new Map(this.joinSchemas);
		next.set(datasourceId, schema);
		this.joinSchemas = next;
	}

	removeJoinDatasource(datasourceId: string): void {
		const next = new Map(this.joinSchemas);
		next.delete(datasourceId);
		this.joinSchemas = next;
	}

	getJoinSchema(datasourceId: string): Schema | null {
		return this.joinSchemas.get(datasourceId) ?? null;
	}

	getJoinSchemaByStepId(stepId: string): Schema | null {
		return this.joinSchemas.get(stepId) ?? null;
	}

	getStepSchemas(): Map<string, StepSchemas> {
		const schemas = new Map<string, StepSchemas>();
		let currentSchema: Schema | null = null;

		const activeTab = analysisStore.activeTab;
		const sourceSchema = activeTab?.datasource_id 
			? analysisStore.sourceSchemas.get(activeTab.datasource_id) ?? null
			: null;

		for (const step of this.steps) {
			const input = currentSchema ?? (sourceSchema ? { columns: sourceSchema.columns, row_count: null } : emptySchema());
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
		this.joinSchemas = new Map();
	}
}

export const schemaStore = new SchemaStore();
