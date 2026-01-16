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
// Handles both frontend format (column_mapping) and backend format (mapping)
export function applyRenameRule(schema: Schema, config: Record<string, unknown>): Schema {
	// Support both column_mapping (frontend) and mapping (backend format)
	const mapping = (config.column_mapping || config.mapping) as Record<string, string>;
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

// TimeSeries transformation: adds new date/time derived columns
export function applyTimeSeriesRule(schema: Schema, config: Record<string, unknown>): Schema {
	const column = config.column as string | undefined;
	const operationType = (config.operationType || config.operation_type) as string | undefined;
	const newColumn = (config.newColumn || config.new_column) as string | undefined;

	if (!column || !operationType || !newColumn) {
		return schema;
	}

	// Check if source column exists
	const sourceCol = schema.columns.find((c) => c.name === column);
	if (!sourceCol) {
		return schema;
	}

	// Determine output dtype based on operation
	let outputDType = 'Int64';
	if (operationType === 'add' || operationType === 'subtract' || operationType === 'diff') {
		outputDType = sourceCol.dtype; // Keep datetime type for date arithmetic
	}

	// Check if we're replacing an existing column
	const existingIndex = schema.columns.findIndex((c) => c.name === newColumn);
	const newCol: Column = {
		name: newColumn,
		dtype: outputDType,
		nullable: true
	};

	const columns =
		existingIndex >= 0
			? schema.columns.map((col, idx) => (idx === existingIndex ? newCol : col))
			: [...schema.columns, newCol];

	return {
		columns,
		row_count: schema.row_count
	};
}

// String transform: modifies or creates string columns
export function applyStringTransformRule(schema: Schema, config: Record<string, unknown>): Schema {
	const column = config.column as string | undefined;
	const method = config.method as string | undefined;
	const newColumn = (config.newColumn || config.new_column || column) as string | undefined;

	if (!column || !method || !newColumn) {
		return schema;
	}

	// Check if source column exists
	const sourceCol = schema.columns.find((c) => c.name === column);
	if (!sourceCol) {
		return schema;
	}

	// Determine output dtype based on method
	let outputDType = 'String';
	if (method === 'length') {
		outputDType = 'Int64';
	}

	// Check if we're replacing an existing column
	const existingIndex = schema.columns.findIndex((c) => c.name === newColumn);
	const newCol: Column = {
		name: newColumn,
		dtype: outputDType,
		nullable: sourceCol.nullable
	};

	const columns =
		existingIndex >= 0
			? schema.columns.map((col, idx) => (idx === existingIndex ? newCol : col))
			: [...schema.columns, newCol];

	return {
		columns,
		row_count: schema.row_count
	};
}

// Fill null transformation: returns same schema (doesn't change structure)
export function applyFillNullRule(schema: Schema, config: Record<string, unknown>): Schema {
	const strategy = config.strategy as string | undefined;
	const columns = config.columns as string[] | undefined;

	// If strategy is 'drop_rows', row count may change
	if (strategy === 'drop_rows') {
		return {
			columns: schema.columns,
			row_count: null
		};
	}

	// For other strategies, schema remains the same
	// Could potentially update nullable to false for affected columns,
	// but keeping it conservative
	return {
		columns: schema.columns,
		row_count: schema.row_count
	};
}

// Deduplicate transformation: returns same schema, row count unknown
export function applyDeduplicateRule(schema: Schema, _config: Record<string, unknown>): Schema {
	return {
		columns: schema.columns,
		row_count: null // Unknown after deduplication
	};
}

// Explode transformation: may change row count
export function applyExplodeRule(schema: Schema, config: Record<string, unknown>): Schema {
	const explodeColumns = config.columns as string | string[] | undefined;
	if (!explodeColumns) {
		return schema;
	}

	const columnsToExplode = Array.isArray(explodeColumns) ? explodeColumns : [explodeColumns];

	return {
		columns: schema.columns.map((col) => {
			if (columnsToExplode.includes(col.name)) {
				// After explode, list type becomes its inner type
				// For simplicity, assuming it becomes the base type (e.g., List[Int64] -> Int64)
				let newDType = col.dtype;
				if (col.dtype.startsWith('List[') && col.dtype.endsWith(']')) {
					newDType = col.dtype.slice(5, -1);
				}
				return { ...col, dtype: newDType };
			}
			return col;
		}),
		row_count: null // Unknown after explode
	};
}

// Pivot transformation: creates new columns based on pivot values
export function applyPivotRule(schema: Schema, config: Record<string, unknown>): Schema {
	const index = config.index as string[] | undefined;
	const pivotColumn = config.columns as string | undefined;
	const values = config.values as string | undefined;

	if (!index || !pivotColumn || !values) {
		return schema;
	}

	// After pivot, we keep index columns but the actual pivoted columns
	// are dynamic based on data values - we can't know them statically
	const indexCols = schema.columns.filter((c) => index.includes(c.name));

	// Since we don't know pivot values, return just index columns
	// The actual pivot columns will be determined at runtime
	return {
		columns: indexCols,
		row_count: null
	};
}

// Unpivot transformation: converts wide to long format
export function applyUnpivotRule(schema: Schema, config: Record<string, unknown>): Schema {
	const index = (config.index || config.id_vars) as string[] | undefined;
	const on = (config.on || config.value_vars) as string[] | undefined;
	const variableName = (config.variable_name || 'variable') as string;
	const valueName = (config.value_name || 'value') as string;

	if (!index) {
		return schema;
	}

	// Keep index columns
	const indexCols = schema.columns.filter((c) => index.includes(c.name));

	// Add variable and value columns
	const columns: Column[] = [
		...indexCols,
		{ name: variableName, dtype: 'String', nullable: false },
		{ name: valueName, dtype: 'String', nullable: true } // Type depends on unpivoted columns
	];

	return {
		columns,
		row_count: null
	};
}

// View transformation: passthrough (doesn't change schema)
export function applyViewRule(schema: Schema, _config: Record<string, unknown>): Schema {
	return {
		columns: schema.columns,
		row_count: schema.row_count
	};
}
