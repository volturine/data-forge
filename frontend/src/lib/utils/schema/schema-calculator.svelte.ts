// Schema Calculator - Client-side schema calculation for pipeline steps
import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import { SvelteMap } from 'svelte/reactivity';
import {
	applyFilterRule,
	applySelectRule,
	applyRenameRule,
	applyGroupByRule,
	applyJoinRule,
	applySortRule,
	applyExpressionRule,
	applyWithColumnRule,
	applyDropRule,
	applyUniqueRule,
	applyCastRule,
	applyTimeSeriesRule,
	applyStringTransformRule,
	applyFillNullRule,
	applyDeduplicateRule,
	applyExplodeRule,
	applyPivotRule,
	applyUnpivotRule,
	applyViewRule
} from './transformation-rules';

class SchemaCalculator {
	// Cache for calculated schemas
	private cache = $state(new SvelteMap<string, Schema>());

	private getStepMap(steps: PipelineStep[]): Map<string, PipelineStep> {
		const stepMap = new Map<string, PipelineStep>();
		for (const step of steps) {
			stepMap.set(step.id, step);
		}
		return stepMap;
	}

	private getDependencyMap(steps: PipelineStep[]): Map<string, string | null> {
		const dependencyMap = new Map<string, string | null>();
		const stepMap = this.getStepMap(steps);
		for (const step of steps) {
			const deps = step.depends_on ?? [];
			if (deps.length > 1) {
				throw new Error(`Step "${step.id}" has multiple dependencies. Merge steps are not supported.`);
			}
			if (deps.length === 0) {
				dependencyMap.set(step.id, null);
				continue;
			}
			const depId = deps[0];
			if (!stepMap.has(depId)) {
				throw new Error(`Step "${step.id}" depends on missing step "${depId}".`);
			}
			dependencyMap.set(step.id, depId);
		}
		return dependencyMap;
	}

	private getDependentsMap(steps: PipelineStep[]): Map<string, string[]> {
		const dependents = new Map<string, string[]>();
		const dependencyMap = this.getDependencyMap(steps);
		for (const [stepId, depId] of dependencyMap.entries()) {
			if (!depId) {
				continue;
			}
			const current = dependents.get(depId) ?? [];
			dependents.set(depId, [...current, stepId]);
		}
		return dependents;
	}

	private topologicalOrder(steps: PipelineStep[]): PipelineStep[] {
		if (steps.length === 0) {
			return [];
		}

		const stepMap = this.getStepMap(steps);
		const dependencyMap = this.getDependencyMap(steps);
		const dependents = new Map<string, string[]>();
		const inDegree = new Map<string, number>();
		for (const step of steps) {
			inDegree.set(step.id, 0);
		}

		for (const [stepId, depId] of dependencyMap.entries()) {
			if (!depId) {
				continue;
			}
			const current = dependents.get(depId) ?? [];
			dependents.set(depId, [...current, stepId]);
			inDegree.set(stepId, (inDegree.get(stepId) ?? 0) + 1);
		}

		const queue = steps.filter((step) => (inDegree.get(step.id) ?? 0) === 0).map((step) => step.id);
		const orderedIds: string[] = [];
		let index = 0;

		while (index < queue.length) {
			const currentId = queue[index];
			index += 1;
			orderedIds.push(currentId);

			const children = dependents.get(currentId) ?? [];
			for (const childId of children) {
				const updated = (inDegree.get(childId) ?? 0) - 1;
				inDegree.set(childId, updated);
				if (updated == 0) {
					queue.push(childId);
				}
			}
		}

		if (orderedIds.length !== steps.length) {
			throw new Error('Pipeline contains a cycle. Remove cyclic dependencies to continue.');
		}

		const orderedSteps: PipelineStep[] = [];
		for (const stepId of orderedIds) {
			const step = stepMap.get(stepId);
			if (!step) {
				throw new Error(`Missing step "${stepId}" while sorting pipeline.`);
			}
			orderedSteps.push(step);
		}
		return orderedSteps;
	}

	private resolveParentId(step: PipelineStep): string | null {
		const deps = step.depends_on ?? [];
		if (deps.length === 0) {
			return null;
		}
		return deps[0];
	}

	invalidateCache(steps: PipelineStep[], rootIds: string[]): void {
		const dependents = this.getDependentsMap(steps);
		const queue = [...rootIds];
		const seen = new Set<string>();
		let index = 0;

		while (index < queue.length) {
			const currentId = queue[index];
			index += 1;
			if (seen.has(currentId)) {
				continue;
			}
			seen.add(currentId);
			const children = dependents.get(currentId) ?? [];
			queue.push(...children);
		}

		for (const stepId of seen) {
			this.cache.delete(stepId);
		}
	}

	private applyPipeline(baseSchema: Schema, steps: PipelineStep[], baseStepId?: string): Map<string, Schema> {
		const schemaMap = new SvelteMap<string, Schema>();
		if (baseStepId) {
			schemaMap.set(baseStepId, baseSchema);
		}

		const orderedSteps = this.topologicalOrder(steps);
		for (const step of orderedSteps) {
			const parentId = this.resolveParentId(step);
			const parentSchema = parentId ? schemaMap.get(parentId) : baseSchema;
			if (!parentSchema) {
				throw new Error(`Missing schema dependency for step "${step.id}".`);
			}

			const cached = this.cache.get(step.id);
			if (cached) {
				schemaMap.set(step.id, cached);
				continue;
			}

			const result = this.applyStep(parentSchema, step, schemaMap);
			if (!result) {
				throw new Error(`Failed to calculate schema for step "${step.id}".`);
			}

			schemaMap.set(step.id, result);
			this.cache.set(step.id, result);
		}

		return schemaMap;
	}

	// Filter: returns same schema
	applyFilter(schema: Schema, config: Record<string, unknown>): Schema {
		return applyFilterRule(schema, config);
	}

	// Select: returns only selected columns
	applySelect(schema: Schema, config: Record<string, unknown>): Schema {
		return applySelectRule(schema, config);
	}

	// Rename: updates column names
	applyRename(schema: Schema, config: Record<string, unknown>): Schema {
		return applyRenameRule(schema, config);
	}

	// GroupBy: returns group keys + aggregation columns
	applyGroupBy(schema: Schema, config: Record<string, unknown>): Schema {
		return applyGroupByRule(schema, config);
	}

	// Join: merges two schemas
	applyJoin(leftSchema: Schema, rightSchema: Schema, config: Record<string, unknown>): Schema {
		return applyJoinRule(leftSchema, rightSchema, config);
	}

	// Sort: returns same schema
	applySort(schema: Schema, config: Record<string, unknown>): Schema {
		return applySortRule(schema, config);
	}

	// Expression: adds new computed column
	applyExpression(schema: Schema, config: Record<string, unknown>): Schema {
		return applyExpressionRule(schema, config);
	}

	// WithColumn: adds or replaces a column
	applyWithColumn(schema: Schema, config: Record<string, unknown>): Schema {
		return applyWithColumnRule(schema, config);
	}

	// Drop: removes columns
	applyDrop(schema: Schema, config: Record<string, unknown>): Schema {
		return applyDropRule(schema, config);
	}

	// Unique: returns same schema
	applyUnique(schema: Schema, config: Record<string, unknown>): Schema {
		return applyUniqueRule(schema, config);
	}

	// Cast: changes column dtype
	applyCast(schema: Schema, config: Record<string, unknown>): Schema {
		return applyCastRule(schema, config);
	}

	// TimeSeries: date/time operations
	applyTimeSeries(schema: Schema, config: Record<string, unknown>): Schema {
		return applyTimeSeriesRule(schema, config);
	}

	// StringTransform: string operations
	applyStringTransform(schema: Schema, config: Record<string, unknown>): Schema {
		return applyStringTransformRule(schema, config);
	}

	// FillNull: handle null values
	applyFillNull(schema: Schema, config: Record<string, unknown>): Schema {
		return applyFillNullRule(schema, config);
	}

	// Deduplicate: remove duplicate rows
	applyDeduplicate(schema: Schema, config: Record<string, unknown>): Schema {
		return applyDeduplicateRule(schema, config);
	}

	// Explode: expand list columns
	applyExplode(schema: Schema, config: Record<string, unknown>): Schema {
		return applyExplodeRule(schema, config);
	}

	// Pivot: reshape wide
	applyPivot(schema: Schema, config: Record<string, unknown>): Schema {
		return applyPivotRule(schema, config);
	}

	// Unpivot: reshape long
	applyUnpivot(schema: Schema, config: Record<string, unknown>): Schema {
		return applyUnpivotRule(schema, config);
	}

	// View: passthrough for visualization
	applyView(schema: Schema, config: Record<string, unknown>): Schema {
		return applyViewRule(schema, config);
	}

	// Apply a single step transformation
	applyStep(schema: Schema, step: PipelineStep, schemaMap?: Map<string, Schema>): Schema | null {
		switch (step.type) {
			case 'filter': {
				return this.applyFilter(schema, step.config);
			}

			case 'select': {
				return this.applySelect(schema, step.config);
			}

			case 'rename': {
				return this.applyRename(schema, step.config);
			}

			case 'group_by':
			case 'groupby': {
				return this.applyGroupBy(schema, step.config);
			}

			case 'join': {
				// Join requires two schemas
				if (!schemaMap) return null;
				const rightId = step.config.right as string | undefined;
				if (!rightId) return null;
				const rightSchema = schemaMap.get(rightId);
				if (!rightSchema) return null;
				return this.applyJoin(schema, rightSchema, step.config);
			}

			case 'sort': {
				return this.applySort(schema, step.config);
			}

			case 'expression':
			case 'with_column':
			case 'with_columns': {
				return this.applyExpression(schema, step.config);
			}

			case 'drop': {
				return this.applyDrop(schema, step.config);
			}

			case 'unique': {
				return this.applyUnique(schema, step.config);
			}

			case 'cast': {
				return this.applyCast(schema, step.config);
			}

			case 'timeseries': {
				return this.applyTimeSeries(schema, step.config);
			}

			case 'string_transform': {
				return this.applyStringTransform(schema, step.config);
			}

			case 'fill_null': {
				return this.applyFillNull(schema, step.config);
			}

			case 'deduplicate': {
				return this.applyDeduplicate(schema, step.config);
			}

			case 'explode': {
				return this.applyExplode(schema, step.config);
			}

			case 'pivot': {
				return this.applyPivot(schema, step.config);
			}

			case 'unpivot': {
				return this.applyUnpivot(schema, step.config);
			}

			case 'view': {
				return this.applyView(schema, step.config);
			}

			default: {
				// Unknown step type, return original schema
				return schema;
			}
		}
	}

	// Calculate schema for a pipeline
	calculatePipelineSchema(
		baseSchema: Schema,
		steps: PipelineStep[],
		baseStepId?: string
	): Schema | null {
		try {
			const schemaMap = this.applyPipeline(baseSchema, steps, baseStepId);
			const orderedSteps = this.topologicalOrder(steps);
			const lastStep = orderedSteps[orderedSteps.length - 1];
			if (!lastStep) {
				return baseSchema;
			}
			return schemaMap.get(lastStep.id) ?? baseSchema;
		} catch (err) {
			console.error(err);
			return null;
		}
	}

	// Get schema for a specific step in the pipeline
	getStepSchema(
		baseSchema: Schema,
		steps: PipelineStep[],
		targetStepId: string,
		baseStepId?: string
	): Schema | null {
		try {
			const schemaMap = this.applyPipeline(baseSchema, steps, baseStepId);
			return schemaMap.get(targetStepId) ?? null;
		} catch (err) {
			console.error(err);
			return null;
		}
	}

	// Clear the cache
	clearCache(): void {
		this.cache.clear();
	}

	// Clear specific cache entries
	clearCacheFor(stepId: string): void {
		this.cache.delete(stepId);
	}
}

// Export singleton instance
export const schemaCalculator = new SchemaCalculator();
