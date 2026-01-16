// Transformation rules for schema calculation
import type { Schema, Column } from '$lib/types/schema';
import { getAggregationResultDType, getExpressionResultDType } from './polars-types';

// Filter transformation: returns same schema (filtering affects rows, not columns)
export function applyFilterRule(schema: Schema, _config: Record<string, unknown>): Schema {
	return {
		columns: schema.columns,
		row_count: null // Unknown after filtering
	};
}

// Select transformation: returns only selected columns
export function applySelectRule(schema: Schema, config: Record<string, unknown>): Schema {
	const columns = config.columns as string[];
	if (!columns || !Array.isArray(columns)) {
		return schema;
	}

	return {
		columns: schema.columns.filter((col) => columns.includes(col.name)),
		row_count: schema.row_count
	};
}

// Rename transformation: updates column names
export function applyRenameRule(schema: Schema, config: Record<string, unknown>): Schema {
	const mapping = config.mapping as Record<string, string>;
	if (!mapping) {
		return schema;
	}

	return {
		columns: schema.columns.map((col) => ({
			...col,
			name: mapping[col.name] || col.name
		})),
		row_count: schema.row_count
	};
}

// GroupBy transformation: returns group keys + aggregation columns
// Handles both camelCase (frontend) and snake_case (backend) property names
export function applyGroupByRule(schema: Schema, config: Record<string, unknown>): Schema {
	// Support both camelCase and snake_case
	const groupBy = (config.groupBy || config.group_by) as string[] | undefined;
	const aggregations = config.aggregations as
		| Array<{ column: string; function: string; alias?: string }>
		| Record<string, string>
		| undefined;

	if (!groupBy || !aggregations) {
		return schema;
	}

	const columns: Column[] = [];

	// Add group by columns (keep original dtype)
	for (const colName of groupBy) {
		const original = schema.columns.find((c) => c.name === colName);
		if (original) {
			columns.push({ ...original });
		}
	}

	// Handle aggregations - can be array format or object format
	if (Array.isArray(aggregations)) {
		// Array format: [{column: 'col', function: 'sum', alias: 'col_sum'}]
		for (const agg of aggregations) {
			const original = schema.columns.find((c) => c.name === agg.column);
			if (!original) continue;

			const resultDType = getAggregationResultDType(agg.function, original.dtype);
			const resultName = agg.alias || `${agg.column}_${agg.function}`;

			columns.push({
				name: resultName,
				dtype: resultDType,
				nullable: original.nullable || agg.function === 'mean' || agg.function === 'median'
			});
		}
	} else {
		// Object format: {colName: 'aggFunc'}
		for (const [colName, aggFunc] of Object.entries(aggregations)) {
			const original = schema.columns.find((c) => c.name === colName);
			if (!original) continue;

			const resultDType = getAggregationResultDType(aggFunc, original.dtype);
			const resultName = `${colName}_${aggFunc}`;

			columns.push({
				name: resultName,
				dtype: resultDType,
				nullable: original.nullable || aggFunc === 'mean' || aggFunc === 'median'
			});
		}
	}

	return {
		columns,
		row_count: null // Unknown after grouping
	};
}

// Join transformation: merges schemas based on join type
export function applyJoinRule(
	leftSchema: Schema,
	rightSchema: Schema,
	config: Record<string, unknown>
): Schema {
	const joinType = (config.how as string) || 'inner';
	const leftOn = config.left_on as string[] | undefined;
	const rightOn = config.right_on as string[] | undefined;
	const suffix = (config.suffix as string) || '_right';

	if (!leftOn || !rightOn) {
		return leftSchema;
	}

	const columns: Column[] = [];
	const addedNames = new Set<string>();

	// Add all left columns
	for (const col of leftSchema.columns) {
		columns.push({
			...col,
			nullable: col.nullable || joinType === 'right' || joinType === 'outer'
		});
		addedNames.add(col.name);
	}

	// Add right columns (excluding join keys)
	for (const col of rightSchema.columns) {
		if (rightOn.includes(col.name)) {
			continue; // Skip join key from right side
		}

		let name = col.name;
		// Handle name conflicts
		if (addedNames.has(name)) {
			name = `${name}${suffix}`;
		}

		columns.push({
			name,
			dtype: col.dtype,
			nullable: col.nullable || joinType === 'left' || joinType === 'outer'
		});
		addedNames.add(name);
	}

	return {
		columns,
		row_count: null // Unknown after join
	};
}

// Sort transformation: returns same schema (sorting affects order, not columns)
export function applySortRule(schema: Schema, _config: Record<string, unknown>): Schema {
	return {
		columns: schema.columns,
		row_count: schema.row_count
	};
}

// Expression transformation: adds a new computed column
export function applyExpressionRule(schema: Schema, config: Record<string, unknown>): Schema {
	const columnName = config.column_name as string | undefined;
	const expression = config.expression as string | undefined;

	if (!columnName || !expression) {
		return schema;
	}

	// Check if column already exists (replace it)
	const existingIndex = schema.columns.findIndex((c) => c.name === columnName);
	const resultDType = getExpressionResultDType(expression, schema);

	const newColumn: Column = {
		name: columnName,
		dtype: resultDType,
		nullable: true // Expressions might produce nulls
	};

	const columns =
		existingIndex >= 0
			? schema.columns.map((col, idx) => (idx === existingIndex ? newColumn : col))
			: [...schema.columns, newColumn];

	return {
		columns,
		row_count: schema.row_count
	};
}

// With column transformation: adds or replaces a column
export function applyWithColumnRule(schema: Schema, config: Record<string, unknown>): Schema {
	return applyExpressionRule(schema, config);
}

// Drop columns transformation: removes specified columns
export function applyDropRule(schema: Schema, config: Record<string, unknown>): Schema {
	const columns = config.columns as string[] | undefined;
	if (!columns || !Array.isArray(columns)) {
		return schema;
	}

	return {
		columns: schema.columns.filter((col) => !columns.includes(col.name)),
		row_count: schema.row_count
	};
}

// Unique transformation: returns same schema
export function applyUniqueRule(schema: Schema, _config: Record<string, unknown>): Schema {
	return {
		columns: schema.columns,
		row_count: null // Unknown after unique
	};
}

// Cast transformation: changes column dtype
export function applyCastRule(schema: Schema, config: Record<string, unknown>): Schema {
	const columnName = config.column as string | undefined;
	const targetDType = config.dtype as string | undefined;

	if (!columnName || !targetDType) {
		return schema;
	}

	return {
		columns: schema.columns.map((col) =>
			col.name === columnName ? { ...col, dtype: targetDType } : col
		),
		row_count: schema.row_count
	};
}
