import type { Schema, ColumnInfo } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { emptySchema } from '$lib/types/schema';
import {
	getStepTransform,
	joinTransform,
	unionByNameTransform,
	type StepConfig
} from '$lib/utils/transform';
import { SvelteMap } from 'svelte/reactivity';

export interface StepSchemas {
	input: Schema;
	output: Schema;
}

class SchemaStore {
	joinSchemas = $state(new SvelteMap<string, Schema>());
	// Cache for actual output schemas from preview (for dynamic steps like pivot)
	previewSchemas = $state(new SvelteMap<string, Schema>());

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

	// Store actual schema from preview response
	setPreviewSchema(stepId: string, columns: string[], columnTypes?: Record<string, string>): void {
		const schemaColumns: ColumnInfo[] = columns.map((name) => ({
			name,
			dtype: columnTypes?.[name] ?? 'Unknown',
			nullable: true
		}));
		this.previewSchemas.set(stepId, { columns: schemaColumns, row_count: null });
	}

	clearPreviewSchema(stepId: string): void {
		this.previewSchemas.delete(stepId);
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

			// Check if we have a cached preview schema for dynamic steps
			const cachedSchema = this.previewSchemas.get(step.id);
			if (cachedSchema && (step.type === 'pivot' || step.type === 'unpivot')) {
				output = cachedSchema;
			} else if (step.type === 'join') {
				const rightSchema = this.joinSchemas.get(step.id) ?? emptySchema();
				const config = step.config as StepConfig;
				output = joinTransform(input, config, rightSchema);
			} else if (step.type === 'union_by_name') {
				const config = step.config as StepConfig;
				const sources = Array.isArray(config.sources) ? config.sources : [];
				const unionSchemas = sources
					.map((sourceId) => this.joinSchemas.get(sourceId))
					.filter((schema): schema is Schema => schema !== undefined);
				output = unionByNameTransform(input, config, unionSchemas);
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
		this.previewSchemas = new SvelteMap();
	}
}

export const schemaStore = new SchemaStore();
