import type { Schema, ColumnInfo } from '$lib/types/schema';
import { analysisStore } from '$lib/stores/analysis.svelte';
import { emptySchema } from '$lib/types/schema';
import {
	getStepTransform,
	joinTransform,
	unionByNameTransform,
	type StepConfig
} from '$lib/utils/transform';
import { resolveColumnType } from '$lib/utils/column-types';
import { isChartStep } from '$lib/components/pipeline/utils';
import { hashPipeline } from '$lib/utils/hash';
import { applySteps } from '$lib/utils/pipeline';
import { SvelteMap } from 'svelte/reactivity';

export interface StepSchemas {
	input: Schema;
	output: Schema;
}

interface PreviewEntry {
	schema: Schema;
	hash: string | null;
}

export class SchemaStore {
	joinSchemas = $state(new SvelteMap<string, Schema>());
	previewSchemas = $state(new SvelteMap<string, PreviewEntry>());

	primaryDatasourceId = $derived(analysisStore.activeTab?.datasource.id ?? null);
	steps = $derived(analysisStore.pipeline);

	stepSchemas = $derived.by(() => {
		const schemas = new SvelteMap<string, StepSchemas>();
		let currentSchema: Schema | null = null;

		const schemaKey = analysisStore.activeSchemaKey;
		const sourceSchema = schemaKey ? (analysisStore.sourceSchemas.get(schemaKey) ?? null) : null;
		const currentHash = hashPipeline(applySteps(this.steps));

		for (const step of this.steps) {
			const input =
				currentSchema ??
				(sourceSchema ? { columns: sourceSchema.columns, row_count: null } : emptySchema());
			const config = step.config as StepConfig;
			const transformer = getStepTransform(step);
			const isApplied = step.is_applied !== false;

			let output: Schema;
			const entry = this.previewSchemas.get(step.id);
			if (!isApplied) {
				output = input;
			} else if (entry && (step.type === 'pivot' || step.type === 'unpivot')) {
				output = entry.schema;
			} else if (entry?.hash !== null && entry?.hash === currentHash && !isChartStep(step.type)) {
				output = entry.schema;
			} else if (step.type === 'join') {
				const rightSource = typeof config.right_source === 'string' ? config.right_source : '';
				const rightSchema = rightSource
					? (this.joinSchemas.get(rightSource) ?? emptySchema())
					: emptySchema();
				output = joinTransform(input, config, rightSchema);
			} else if (step.type === 'union_by_name') {
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
	});

	setJoinDatasource(datasourceId: string, schema: Schema): void {
		this.joinSchemas.set(datasourceId, schema);
	}

	removeJoinDatasource(datasourceId: string): void {
		this.joinSchemas.delete(datasourceId);
	}

	getJoinSchema(datasourceId: string): Schema | null {
		return this.joinSchemas.get(datasourceId) ?? null;
	}

	syncPreviewSchema(
		stepId: string,
		response: { columns?: string[]; column_types?: Record<string, string> },
		pipelineHash: string
	): void {
		if (!response.columns?.length || !response.column_types) return;
		this.setPreviewSchema(stepId, response.columns, response.column_types, pipelineHash);
	}

	setPreviewSchema(
		stepId: string,
		columns: string[],
		columnTypes?: Record<string, string>,
		pipelineHash?: string | null
	): void {
		const schemaColumns: ColumnInfo[] = columns.map((name) => ({
			name,
			dtype: resolveColumnType(columnTypes?.[name]),
			nullable: true
		}));
		this.previewSchemas.set(stepId, {
			schema: { columns: schemaColumns, row_count: null },
			hash: pipelineHash ?? null
		});
	}

	clearPreviewSchema(stepId: string): void {
		this.previewSchemas.delete(stepId);
	}

	getInput(stepId: string): Schema | null {
		return this.stepSchemas.get(stepId)?.input ?? null;
	}

	getOutput(stepId: string): Schema | null {
		return this.stepSchemas.get(stepId)?.output ?? null;
	}

	getAllOutputs(): Schema[] {
		return this.steps.map((step) => this.getOutput(step.id)).filter((s): s is Schema => s !== null);
	}

	getLastOutput(): Schema | null {
		const last = this.steps.at(-1);
		return last ? this.getOutput(last.id) : null;
	}

	reset(): void {
		this.joinSchemas = new SvelteMap();
		this.previewSchemas = new SvelteMap();
	}
}

export const schemaStore = new SchemaStore();
