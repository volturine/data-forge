import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import type { ColumnInfo } from '$lib/types/schema';
import {
	emptySchema,
	unionByName,
	intersectSchemas,
	leftJoinSchema,
	rightJoinSchema,
	outerJoinSchema,
	crossJoinSchema
} from '$lib/types/schema';

export interface StepConfig {
	conditions?: Array<{ column: string; operator: string; value: string }>;
	logic?: string;
	columns?: string[];
	groupBy?: string[];
	aggregations?:
		| Array<{ column: string; function?: string; agg?: string; alias?: string }>
		| Record<string, string | Array<{ column: string; agg: string }>>;
	sort_by?: Array<{ column: string; descending: boolean }>;
	mapping?: Record<string, string>;
	column_mapping?: Record<string, string>;
	right?: string;
	how?: string;
	left_on?: string | null;
	right_on?: string | null;
	datasource_id?: string;
	suffix?: string;
	expression?: string;
	fill_value?: string | number;
	value_type?: string;
	strategy?: string;
	target_column?: string;
	columns_to_keep?: string[];
	explode_column?: string;
	window?: Record<string, unknown>;
	rowLimit?: number;
	join_columns?: Array<{ id: string; left_column: string; right_column: string }>;
	right_columns?: string[];
	sources?: string[];
	allow_missing?: boolean;
	expressions?: Array<{
		name: string;
		type: string;
		value?: string | number | null;
		column?: string | null;
		args?: string[] | null;
		code?: string | null;
	}>;
	[key: string]: unknown;
}

export type SchemaTransformer = (input: Schema | null, config: StepConfig) => Schema;

const EMPTY: Schema = { columns: [], row_count: null };
function passthrough(input: Schema | null): Schema {
	return input ?? EMPTY;
}
function clearCount(input: Schema | null): Schema {
	if (!input) return EMPTY;
	return { columns: input.columns, row_count: null };
}

export function selectTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const columns = config.columns as string[] | undefined;
	if (!columns || columns.length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: input.columns.filter((col) => columns.includes(col.name)),
		row_count: null
	};
}

export function dropTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const columns = config.columns as string[] | undefined;
	if (!columns || columns.length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: input.columns.filter((col) => !columns.includes(col.name)),
		row_count: null
	};
}

export function renameTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const mapping = (config.mapping ?? config.column_mapping) as Record<string, string> | undefined;
	if (!mapping || Object.keys(mapping).length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: input.columns.map((col) => ({
			...col,
			name: mapping[col.name] ?? col.name
		})),
		row_count: null
	};
}

export function groupbyTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const groupBy = config.groupBy as string[] | undefined;
	const aggregations = config.aggregations as
		| Array<{ column: string; function?: string; agg?: string; alias?: string }>
		| Record<string, string | Array<{ column: string; agg: string }>>
		| undefined;

	const result: typeof input.columns = [];

	result.push(
		...(groupBy ?? []).map((col) => ({
			name: col,
			dtype: normalizeDtype(input.columns.find((column) => column.name === col)?.dtype) ?? 'Any',
			nullable: false
		}))
	);

	if (Array.isArray(aggregations)) {
		result.push(
			...aggregations
				.filter((agg) => agg.column && (agg.function ?? agg.agg))
				.map((agg) => ({
					name: agg.alias || `${agg.column}_${agg.function ?? agg.agg}`,
					dtype: 'Float64' as const,
					nullable: true
				}))
		);
		return { columns: result, row_count: null };
	}

	for (const [aggColumn, aggFunc] of Object.entries(aggregations ?? {})) {
		let aggName: string;

		if (typeof aggFunc === 'string') {
			aggName = `${aggColumn}_${aggFunc}`;
		} else if (Array.isArray(aggFunc)) {
			aggName = `${aggColumn}_${aggFunc.map((a) => a.agg).join('_')}`;
		} else {
			aggName = `${aggColumn}_${(aggFunc as { column: string; agg: string }).agg}`;
		}

		result.push({
			name: aggName,
			dtype: 'Float64',
			nullable: true
		});
	}

	return { columns: result, row_count: null };
}

export function fillNullTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const strategy = config.strategy as string | undefined;
	const fillType = normalizeDtype(config.value_type as string | undefined);
	const targets = config.columns ?? null;
	const clearsNulls = strategy !== undefined;

	return {
		columns: input.columns.map((column) => {
			const isTarget = !targets || targets.includes(column.name);
			if (!isTarget) return column;
			const dtype = fillType ?? normalizeDtype(column.dtype) ?? column.dtype;
			const nullable = clearsNulls ? false : column.nullable;
			return { ...column, dtype, nullable };
		}),
		row_count: null
	};
}

export function withColumnsTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;
	const expressions = config.expressions ?? [];
	if (!Array.isArray(expressions) || expressions.length === 0) {
		return { columns: input.columns, row_count: null };
	}

	const inputMap = new Map(input.columns.map((col) => [col.name, col]));
	const additions = expressions
		.map((expr) => {
			const name = typeof expr.name === 'string' ? expr.name : '';
			if (!name) return null;
			if (expr.type === 'column' && typeof expr.column === 'string') {
				const source = inputMap.get(expr.column);
				if (source) {
					return { ...source, name };
				}
			}
			return { name, dtype: 'Any', nullable: true };
		})
		.filter((col): col is ColumnInfo => col !== null);

	const additionsByName = new Map(additions.map((col) => [col.name, col]));
	const updated = input.columns.map((col) => additionsByName.get(col.name) ?? col);
	const appendOrder = additions.filter((col) => !inputMap.has(col.name));
	const seen = new Set<string>();
	const append = appendOrder
		.reverse()
		.filter((col) => !seen.has(col.name) && (seen.add(col.name), true))
		.reverse();

	return {
		columns: [...updated, ...append],
		row_count: null
	};
}

export function pivotTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const index = config.index as string[] | undefined;

	if (!index || index.length === 0) {
		return EMPTY;
	}

	const indexColumns = input.columns.filter((col) => index.includes(col.name));

	return { columns: indexColumns, row_count: null };
}

export function unpivotTransform(input: Schema | null, _config: StepConfig): Schema {
	if (!input) return EMPTY;

	return {
		columns: [
			{ name: 'variable', dtype: 'Utf8', nullable: false },
			{ name: 'value', dtype: 'Any', nullable: true }
		],
		row_count: null
	};
}

export function explodeTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const column = config.explode_column as string | undefined;
	const hasColumn = input.columns.some((col) => col.name === column);

	return {
		columns: hasColumn ? input.columns.filter((col) => col.name !== column) : input.columns,
		row_count: null
	};
}

export function stringTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const source = config.column as string | undefined;
	const newColumn = (config.new_column ?? config.newColumn ?? source) as string | undefined;
	if (!source || !newColumn) {
		return { columns: input.columns, row_count: null };
	}

	const exists = input.columns.some((col) => col.name === newColumn);
	if (newColumn === source || exists) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: [...input.columns, { name: newColumn, dtype: 'Any', nullable: true }],
		row_count: null
	};
}

export function timeseriesTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;
	const column = config.column as string | undefined;
	const newColumn = config.new_column as string | undefined;
	const operationType = config.operation_type as string | undefined;
	if (!newColumn || !operationType) return passthrough(input);

	let dtype: string;
	if (operationType === 'extract') dtype = 'Int32';
	else if (operationType === 'timestamp') dtype = 'Int64';
	else if (operationType === 'diff') dtype = 'Duration';
	else dtype = input.columns.find((c) => c.name === column)?.dtype ?? 'Datetime';

	const newCol: ColumnInfo = { name: newColumn, dtype, nullable: false };
	const exists = input.columns.some((c) => c.name === newColumn);
	return {
		columns: exists
			? input.columns.map((c) => (c.name === newColumn ? newCol : c))
			: [...input.columns, newCol],
		row_count: null
	};
}

export function nullCountTransform(input: Schema | null, _config: StepConfig): Schema {
	if (!input) return EMPTY;

	return {
		columns: input.columns.map((col) => ({
			name: `${col.name}_null_count`,
			dtype: 'UInt32',
			nullable: false
		})),
		row_count: null
	};
}

export function valueCountsTransform(input: Schema | null, _config: StepConfig): Schema {
	if (!input) return EMPTY;

	return {
		columns: [
			{ name: 'value', dtype: 'Any', nullable: false },
			{ name: 'count', dtype: 'UInt32', nullable: false }
		],
		row_count: null
	};
}

export function expressionTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return EMPTY;

	const expression = config.expression as string | undefined;
	const columnName =
		(config.column_name as string | undefined) || (config.target_column as string | undefined);

	if (!expression || !columnName) {
		return { columns: input.columns, row_count: null };
	}

	const exists = input.columns.some((c) => c.name === columnName);
	if (exists) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: [...input.columns, { name: columnName, dtype: 'Any', nullable: true }],
		row_count: null
	};
}

export function joinTransform(
	input: Schema | null,
	config: StepConfig,
	rightSchema: Schema | null
): Schema {
	if (!input) return rightSchema ?? EMPTY;

	const how = (config.how as string) ?? 'inner';
	const suffix = (config.suffix as string) ?? '_right';

	const rightColumns = config.right_columns as string[] | undefined;

	const safeRightSchema = rightSchema ?? EMPTY;

	switch (how) {
		case 'inner':
			return intersectSchemas(input, safeRightSchema, suffix, rightColumns);
		case 'left':
			return leftJoinSchema(input, safeRightSchema, suffix, rightColumns);
		case 'right':
			return rightJoinSchema(input, safeRightSchema, suffix, rightColumns);
		case 'outer':
			return outerJoinSchema(input, safeRightSchema, suffix, rightColumns);
		case 'cross':
			return crossJoinSchema(input, safeRightSchema);
		default:
			return intersectSchemas(input, safeRightSchema, suffix, rightColumns);
	}
}

export function unionByNameTransform(
	input: Schema | null,
	config: StepConfig,
	unionSchemas: Schema[]
): Schema {
	if (!input) return emptySchema();

	const allowMissing = config.allow_missing !== false;
	const schemas = [input, ...unionSchemas];
	const merged = unionByName(schemas, allowMissing);

	if (allowMissing) return merged;

	const baseNames = new Set(input.columns.map((col) => col.name));
	const sameColumns = unionSchemas.every((schema) => {
		if (schema.columns.length !== baseNames.size) return false;
		return schema.columns.every((col) => baseNames.has(col.name));
	});

	return sameColumns ? merged : input;
}

export function normalizeDtype(dtype: string | undefined): string | undefined {
	if (!dtype) return undefined;
	const map: Record<string, string> = {
		i64: 'Int64',
		f64: 'Float64',
		bool: 'Boolean',
		str: 'Utf8',
		date: 'Date',
		datetime: 'Datetime',
		unknown: 'Any'
	};
	return map[dtype] ?? dtype;
}

const TRANSFORMERS: Record<string, SchemaTransformer> = {
	filter: clearCount,
	select: selectTransform,
	drop: dropTransform,
	rename: renameTransform,
	groupby: groupbyTransform,
	sort: passthrough,
	fill_null: fillNullTransform,
	deduplicate: clearCount,
	with_columns: withColumnsTransform,
	pivot: pivotTransform,
	unpivot: unpivotTransform,
	explode: explodeTransform,
	timeseries: timeseriesTransform,
	string_transform: stringTransform,
	sample: clearCount,
	limit: clearCount,
	topk: clearCount,
	null_count: nullCountTransform,
	value_counts: valueCountsTransform,
	view: passthrough,
	export: passthrough,
	expression: expressionTransform
};

export function getStepTransform(step: PipelineStep): SchemaTransformer {
	if (step.type.startsWith('plot_')) return passthrough;
	return TRANSFORMERS[step.type] ?? passthrough;
}
