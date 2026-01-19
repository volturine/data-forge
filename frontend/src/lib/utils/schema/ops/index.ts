import type { Schema } from '$lib/types/schema';
import type { PipelineStep } from '$lib/types/analysis';
import {
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
	aggregations?: Record<string, string | Array<{ column: string; agg: string }>>;
	sort_by?: Array<{ column: string; descending: boolean }>;
	mapping?: Record<string, string>;
	right?: string;
	how?: string;
	left_on?: string | null;
	right_on?: string | null;
	datasource_id?: string;
	suffix?: string;
	expression?: string;
	fill_value?: string | number;
	strategy?: string;
	target_column?: string;
	columns_to_keep?: string[];
	explode_column?: string;
	window?: Record<string, unknown>;
	rowLimit?: number;
	[ key: string ]: unknown;
}

export type SchemaTransformer = (input: Schema | null, config: StepConfig) => Schema;

export function filterTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const conditions = config.conditions as Array<{ column: string; operator: string; value: string }> | undefined;
	if (!conditions || conditions.length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return { columns: input.columns, row_count: null };
}

export function selectTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const columns = config.columns as string[] | undefined;
	if (!columns || columns.length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: input.columns.filter(c => columns.includes(c.name)),
		row_count: null
	};
}

export function dropTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const columns = config.columns as string[] | undefined;
	if (!columns || columns.length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: input.columns.filter(c => !columns.includes(c.name)),
		row_count: null
	};
}

export function renameTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const mapping = config.mapping as Record<string, string> | undefined;
	if (!mapping || Object.keys(mapping).length === 0) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: input.columns.map(c => ({
			...c,
			name: mapping[c.name] ?? c.name
		})),
		row_count: null
	};
}

export function groupbyTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const groupBy = config.groupBy as string[] | undefined;
	const aggregations = config.aggregations as Record<string, string | Array<{ column: string; agg: string }>> | undefined;

	const result: typeof input.columns = [];

	for (const col of groupBy ?? []) {
		result.push({
			name: col,
			dtype: input.columns.find(c => c.name === col)?.dtype ?? 'unknown',
			nullable: false
		});
	}

	for (const [aggColumn, aggFunc] of Object.entries(aggregations ?? {})) {
		const origCol = input.columns.find(c => c.name === aggColumn);
		let aggName: string;

		if (typeof aggFunc === 'string') {
			aggName = `${aggColumn}_${aggFunc}`;
		} else if (Array.isArray(aggFunc)) {
			// Multiple aggregations on same column
			aggName = `${aggColumn}_${aggFunc.map(a => a.agg).join('_')}`;
		} else {
			aggName = `${aggColumn}_${(aggFunc as { column: string; agg: string }).agg}`;
		}

		result.push({
			name: aggName,
			dtype: 'f64',
			nullable: true
		});
	}

	return { columns: result, row_count: null };
}

export function sortTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function fillNullTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const strategy = config.strategy as string | undefined;
	const fillValue = config.fill_value;

	return {
		columns: input.columns.map(c => {
			if (c.nullable) {
				return { ...c, nullable: strategy !== 'drop' };
			}
			return c;
		}),
		row_count: null
	};
}

export function deduplicateTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function withColumnsTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const expression = config.expression as string | undefined;
	const targetColumn = config.target_column as string | undefined;

	if (!expression || !targetColumn) {
		return { columns: input.columns, row_count: null };
	}

	const newColumn: typeof input.columns[0] = {
		name: targetColumn,
		dtype: 'unknown',
		nullable: true
	};

	return {
		columns: [...input.columns, newColumn],
		row_count: null
	};
}

export function pivotTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function unpivotTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return {
		columns: [
			{ name: 'variable', dtype: 'str', nullable: false },
			{ name: 'value', dtype: 'unknown', nullable: true }
		],
		row_count: null
	};
}

export function explodeTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const column = config.explode_column as string | undefined;
	const origCol = input.columns.find(c => c.name === column);

	return {
		columns: origCol ? input.columns.filter(c => c.name !== column) : input.columns,
		row_count: null
	};
}

export function timeseriesTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function stringTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function sampleTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function limitTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function topkTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return { columns: input.columns, row_count: null };
}

export function nullCountTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return {
		columns: input.columns.map(c => ({
			name: `${c.name}_null_count`,
			dtype: 'u32',
			nullable: false
		})),
		row_count: null
	};
}

export function valueCountsTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	return {
		columns: [
			{ name: 'value', dtype: 'unknown', nullable: false },
			{ name: 'count', dtype: 'u32', nullable: false }
		],
		row_count: null
	};
}

export function viewTransform(input: Schema | null, config: StepConfig): Schema {
	return input ?? { columns: [], row_count: null };
}

export function exportTransform(input: Schema | null, config: StepConfig): Schema {
	return input ?? { columns: [], row_count: null };
}

export function expressionTransform(input: Schema | null, config: StepConfig): Schema {
	if (!input) return { columns: [], row_count: null };

	const expression = config.expression as string | undefined;
	const targetColumn = config.target_column as string | undefined;

	if (!expression || !targetColumn) {
		return { columns: input.columns, row_count: null };
	}

	return {
		columns: [...input.columns, { name: targetColumn, dtype: 'unknown', nullable: true }],
		row_count: null
	};
}

export function joinTransform(
	input: Schema | null,
	config: StepConfig,
	rightSchema: Schema | null
): Schema {
	if (!input) return rightSchema ?? { columns: [], row_count: null };
	if (!rightSchema) return { columns: input.columns, row_count: null };

	const how = config.how as string ?? 'inner';
	const suffix = (config.suffix as string) ?? '_right';

	switch (how) {
		case 'inner':
			return intersectSchemas(input, rightSchema, suffix);
		case 'left':
			return leftJoinSchema(input, rightSchema, suffix);
		case 'right':
			return rightJoinSchema(input, rightSchema, suffix);
		case 'outer':
			return outerJoinSchema(input, rightSchema, suffix);
		case 'cross':
			return crossJoinSchema(input, rightSchema);
		default:
			return intersectSchemas(input, rightSchema, suffix);
	}
}

export function getStepTransform(step: PipelineStep): SchemaTransformer {
	const transformers: Record<string, SchemaTransformer> = {
		filter: filterTransform,
		select: selectTransform,
		drop: dropTransform,
		rename: renameTransform,
		groupby: groupbyTransform,
		sort: sortTransform,
		fill_null: fillNullTransform,
		deduplicate: deduplicateTransform,
		with_columns: withColumnsTransform,
		pivot: pivotTransform,
		unpivot: unpivotTransform,
		explode: explodeTransform,
		timeseries: timeseriesTransform,
		string_transform: stringTransform,
		sample: sampleTransform,
		limit: limitTransform,
		topk: topkTransform,
		null_count: nullCountTransform,
		value_counts: valueCountsTransform,
		view: viewTransform,
		export: exportTransform,
		expression: expressionTransform
	};

	return transformers[step.type] ?? ((input) => input ?? { columns: [], row_count: null });
}
