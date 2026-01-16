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
	applyCastRule
} from './transformation-rules';

class SchemaCalculator {
	// Cache for calculated schemas
	private cache = $state(new SvelteMap<string, Schema>());

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
		const schemaMap = new SvelteMap<string, Schema>();

		// Set base schema
		if (baseStepId) {
			schemaMap.set(baseStepId, baseSchema);
		}

		let currentSchema = baseSchema;

		// Apply each step sequentially
		for (const step of steps) {
			// Check dependencies
			if (step.depends_on && step.depends_on.length > 0) {
				// Use schema from the last dependency
				const lastDep = step.depends_on[step.depends_on.length - 1];
				const depSchema = schemaMap.get(lastDep);
				if (depSchema) {
					currentSchema = depSchema;
				}
			}

			// Apply transformation
			const result = this.applyStep(currentSchema, step, schemaMap);
			if (!result) {
				// Failed to calculate schema for this step
				return null;
			}

			currentSchema = result;
			schemaMap.set(step.id, currentSchema);
		}

		return currentSchema;
	}

	// Get schema for a specific step in the pipeline
	getStepSchema(
		baseSchema: Schema,
		steps: PipelineStep[],
		targetStepId: string,
		baseStepId?: string
	): Schema | null {
		const cacheKey = `${baseStepId || 'base'}-${targetStepId}`;

		// Check cache
		if (this.cache.has(cacheKey)) {
			return this.cache.get(cacheKey)!;
		}

		const schemaMap = new SvelteMap<string, Schema>();

		// Set base schema
		if (baseStepId) {
			schemaMap.set(baseStepId, baseSchema);
		}

		let currentSchema = baseSchema;

		// Apply steps until we reach the target
		for (const step of steps) {
			// Check dependencies
			if (step.depends_on && step.depends_on.length > 0) {
				const lastDep = step.depends_on[step.depends_on.length - 1];
				const depSchema = schemaMap.get(lastDep);
				if (depSchema) {
					currentSchema = depSchema;
				}
			}

			// Apply transformation
			const result = this.applyStep(currentSchema, step, schemaMap);
			if (!result) {
				return null;
			}

			currentSchema = result;
			schemaMap.set(step.id, currentSchema);

			// Stop if we reached the target
			if (step.id === targetStepId) {
				this.cache.set(cacheKey, currentSchema);
				return currentSchema;
			}
		}

		return null;
	}

	// Clear the cache
	clearCache(): void {
		this.cache.clear();
	}

	// Clear specific cache entries
	clearCacheFor(stepId: string): void {
		const keysToDelete: string[] = [];
		for (const key of this.cache.keys()) {
			if (key.includes(stepId)) {
				keysToDelete.push(key);
			}
		}
		for (const key of keysToDelete) {
			this.cache.delete(key);
		}
	}
}

// Export singleton instance
export const schemaCalculator = new SchemaCalculator();
