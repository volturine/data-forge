import { describe, test, expect } from 'vitest';
import type { Schema } from '$lib/types/schema';
import type { StepConfig } from './transform';
import {
	normalizeDtype,
	selectTransform,
	dropTransform,
	renameTransform,
	groupbyTransform,
	fillNullTransform,
	withColumnsTransform,
	pivotTransform,
	unpivotTransform,
	explodeTransform,
	stringTransform,
	timeseriesTransform,
	nullCountTransform,
	valueCountsTransform,
	expressionTransform,
	joinTransform,
	unionByNameTransform,
	getStepTransform
} from './transform';

const EMPTY: Schema = { columns: [], row_count: null };

function schema(cols: Array<{ name: string; dtype: string; nullable?: boolean }>): Schema {
	return {
		columns: cols.map((c) => ({ name: c.name, dtype: c.dtype, nullable: c.nullable ?? false })),
		row_count: 10
	};
}

const BASE = schema([
	{ name: 'id', dtype: 'Int64' },
	{ name: 'name', dtype: 'Utf8' },
	{ name: 'age', dtype: 'Int64' },
	{ name: 'city', dtype: 'Utf8', nullable: true }
]);

// ── normalizeDtype ──────────────────────────────────────────────────────────

describe('normalizeDtype', () => {
	test('maps known shorthand types', () => {
		expect(normalizeDtype('i64')).toBe('Int64');
		expect(normalizeDtype('f64')).toBe('Float64');
		expect(normalizeDtype('bool')).toBe('Boolean');
		expect(normalizeDtype('str')).toBe('Utf8');
		expect(normalizeDtype('date')).toBe('Date');
		expect(normalizeDtype('datetime')).toBe('Datetime');
		expect(normalizeDtype('unknown')).toBe('Any');
	});

	test('passes through already-canonical types', () => {
		expect(normalizeDtype('Int64')).toBe('Int64');
		expect(normalizeDtype('Float64')).toBe('Float64');
		expect(normalizeDtype('Utf8')).toBe('Utf8');
	});

	test('returns undefined for undefined input', () => {
		expect(normalizeDtype(undefined)).toBeUndefined();
	});

	test('returns empty string as-is (not in map)', () => {
		expect(normalizeDtype('')).toBeUndefined();
	});
});

// ── selectTransform ─────────────────────────────────────────────────────────

describe('selectTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(selectTransform(null, { columns: ['id'] })).toEqual(EMPTY);
	});

	test('returns all columns when columns config is empty', () => {
		const result = selectTransform(BASE, { columns: [] });
		expect(result.columns).toEqual(BASE.columns);
		expect(result.row_count).toBeNull();
	});

	test('returns all columns when columns config is undefined', () => {
		const result = selectTransform(BASE, {});
		expect(result.columns).toEqual(BASE.columns);
	});

	test('selects specific columns preserving order', () => {
		const result = selectTransform(BASE, { columns: ['age', 'name'] });
		expect(result.columns.map((c) => c.name)).toEqual(['name', 'age']);
	});

	test('applies cast_map to selected columns', () => {
		const result = selectTransform(BASE, {
			columns: ['age'],
			cast_map: { age: 'f64' }
		});
		expect(result.columns[0].dtype).toBe('Float64');
	});

	test('preserves dtype when column not in cast_map', () => {
		const result = selectTransform(BASE, {
			columns: ['id', 'age'],
			cast_map: { age: 'str' }
		});
		expect(result.columns[0].dtype).toBe('Int64');
		expect(result.columns[1].dtype).toBe('Utf8');
	});

	test('ignores nonexistent columns in selection', () => {
		const result = selectTransform(BASE, { columns: ['id', 'nonexistent'] });
		expect(result.columns).toHaveLength(1);
		expect(result.columns[0].name).toBe('id');
	});

	test('clears row_count', () => {
		const result = selectTransform(BASE, { columns: ['id'] });
		expect(result.row_count).toBeNull();
	});
});

// ── dropTransform ───────────────────────────────────────────────────────────

describe('dropTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(dropTransform(null, { columns: ['id'] })).toEqual(EMPTY);
	});

	test('returns all columns when columns config is empty', () => {
		const result = dropTransform(BASE, { columns: [] });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('returns all columns when columns config is undefined', () => {
		const result = dropTransform(BASE, {});
		expect(result.columns).toEqual(BASE.columns);
	});

	test('drops specified columns', () => {
		const result = dropTransform(BASE, { columns: ['id', 'city'] });
		expect(result.columns.map((c) => c.name)).toEqual(['name', 'age']);
	});

	test('ignores nonexistent columns', () => {
		const result = dropTransform(BASE, { columns: ['nonexistent'] });
		expect(result.columns).toHaveLength(4);
	});
});

// ── renameTransform ─────────────────────────────────────────────────────────

describe('renameTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(renameTransform(null, { column_mapping: { id: 'pk' } })).toEqual(EMPTY);
	});

	test('returns all columns when column_mapping is empty', () => {
		const result = renameTransform(BASE, { column_mapping: {} });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('returns all columns when column_mapping is undefined', () => {
		const result = renameTransform(BASE, {});
		expect(result.columns).toEqual(BASE.columns);
	});

	test('renames columns via column_mapping', () => {
		const result = renameTransform(BASE, { column_mapping: { id: 'pk', name: 'full_name' } });
		expect(result.columns[0].name).toBe('pk');
		expect(result.columns[1].name).toBe('full_name');
		expect(result.columns[2].name).toBe('age');
	});

	test('falls back to mapping when column_mapping is absent', () => {
		const result = renameTransform(BASE, { mapping: { city: 'location' } });
		expect(result.columns[3].name).toBe('location');
	});

	test('preserves dtype and nullable through rename', () => {
		const result = renameTransform(BASE, { column_mapping: { city: 'location' } });
		expect(result.columns[3].dtype).toBe('Utf8');
		expect(result.columns[3].nullable).toBe(true);
	});
});

// ── groupbyTransform ────────────────────────────────────────────────────────

describe('groupbyTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(groupbyTransform(null, {})).toEqual(EMPTY);
	});

	test('produces group columns from group_by', () => {
		const result = groupbyTransform(BASE, { group_by: ['city'] });
		expect(result.columns[0].name).toBe('city');
		expect(result.columns[0].dtype).toBe('Utf8');
	});

	test('produces aggregation columns from array-format aggregations', () => {
		const result = groupbyTransform(BASE, {
			group_by: ['city'],
			aggregations: [
				{ column: 'age', function: 'mean' },
				{ column: 'id', agg: 'count', alias: 'id_count' }
			]
		});
		expect(result.columns).toHaveLength(3);
		expect(result.columns[1].name).toBe('age_mean');
		expect(result.columns[1].dtype).toBe('Float64');
		expect(result.columns[2].name).toBe('id_count');
	});

	test('skips aggregations missing column or function', () => {
		const result = groupbyTransform(BASE, {
			group_by: ['city'],
			aggregations: [
				{ column: '', function: 'mean' },
				{ column: 'age', function: '' }
			]
		});
		expect(result.columns).toHaveLength(1);
	});

	test('produces aggregation columns from record-format aggregations', () => {
		const result = groupbyTransform(BASE, {
			group_by: [],
			aggregations: { age: 'mean', name: 'count' }
		});
		expect(result.columns.map((c) => c.name)).toEqual(['age_mean', 'name_count']);
	});

	test('handles record-format with array agg spec', () => {
		const result = groupbyTransform(BASE, {
			group_by: [],
			aggregations: { age: [{ column: 'age', agg: 'sum' }] }
		});
		expect(result.columns[0].name).toBe('age_sum');
	});

	test('returns only group_by columns when aggregations undefined', () => {
		const result = groupbyTransform(BASE, { group_by: ['id'] });
		expect(result.columns).toHaveLength(1);
		expect(result.columns[0].name).toBe('id');
	});

	test('resolves dtype for group columns from input', () => {
		const result = groupbyTransform(BASE, { group_by: ['age'] });
		expect(result.columns[0].dtype).toBe('Int64');
	});

	test('uses Any for group column not found in input', () => {
		const result = groupbyTransform(BASE, { group_by: ['missing'] });
		expect(result.columns[0].dtype).toBe('Any');
	});
});

// ── fillNullTransform ───────────────────────────────────────────────────────

describe('fillNullTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(fillNullTransform(null, {})).toEqual(EMPTY);
	});

	test('clears nullable when strategy is specified', () => {
		const result = fillNullTransform(BASE, { strategy: 'forward', columns: ['city'] });
		const city = result.columns.find((c) => c.name === 'city')!;
		expect(city.nullable).toBe(false);
	});

	test('applies to all columns when columns config is null', () => {
		const input = schema([
			{ name: 'a', dtype: 'Int64', nullable: true },
			{ name: 'b', dtype: 'Utf8', nullable: true }
		]);
		const result = fillNullTransform(input, { strategy: 'zero' });
		expect(result.columns.every((c) => !c.nullable)).toBe(true);
	});

	test('applies value_type override to targeted columns', () => {
		const result = fillNullTransform(BASE, {
			columns: ['age'],
			value_type: 'f64'
		});
		expect(result.columns.find((c) => c.name === 'age')!.dtype).toBe('Float64');
		expect(result.columns.find((c) => c.name === 'id')!.dtype).toBe('Int64');
	});

	test('leaves non-target columns unchanged', () => {
		const result = fillNullTransform(BASE, { strategy: 'zero', columns: ['city'] });
		expect(result.columns.find((c) => c.name === 'id')!.nullable).toBe(false);
	});
});

// ── withColumnsTransform ────────────────────────────────────────────────────

describe('withColumnsTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(withColumnsTransform(null, {})).toEqual(EMPTY);
	});

	test('returns input columns when expressions empty', () => {
		const result = withColumnsTransform(BASE, { expressions: [] });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('adds new column from literal expression', () => {
		const result = withColumnsTransform(BASE, {
			expressions: [{ name: 'score', type: 'literal', value: 100 }]
		});
		expect(result.columns).toHaveLength(5);
		expect(result.columns[4].name).toBe('score');
		expect(result.columns[4].dtype).toBe('Any');
	});

	test('overwrites existing column preserving position', () => {
		const result = withColumnsTransform(BASE, {
			expressions: [{ name: 'age', type: 'literal', value: 0 }]
		});
		expect(result.columns).toHaveLength(4);
		expect(result.columns[2].name).toBe('age');
		expect(result.columns[2].dtype).toBe('Any');
	});

	test('copies dtype from source column for column type', () => {
		const result = withColumnsTransform(BASE, {
			expressions: [{ name: 'age_copy', type: 'column', column: 'age' }]
		});
		const copy = result.columns.find((c) => c.name === 'age_copy')!;
		expect(copy.dtype).toBe('Int64');
	});

	test('skips expressions with empty name', () => {
		const result = withColumnsTransform(BASE, {
			expressions: [{ name: '', type: 'literal', value: 1 }]
		});
		expect(result.columns).toHaveLength(4);
	});

	test('deduplicates appended columns by name', () => {
		const result = withColumnsTransform(BASE, {
			expressions: [
				{ name: 'new_col', type: 'literal', value: 1 },
				{ name: 'new_col', type: 'literal', value: 2 }
			]
		});
		const newCols = result.columns.filter((c) => c.name === 'new_col');
		expect(newCols).toHaveLength(1);
	});
});

// ── pivotTransform ──────────────────────────────────────────────────────────

describe('pivotTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(pivotTransform(null, {})).toEqual(EMPTY);
	});

	test('returns EMPTY when index is empty', () => {
		expect(pivotTransform(BASE, { index: [] })).toEqual(EMPTY);
	});

	test('returns EMPTY when index is undefined', () => {
		expect(pivotTransform(BASE, {})).toEqual(EMPTY);
	});

	test('returns only index columns from input', () => {
		const config: StepConfig = { index: ['id', 'city'] };
		const result = pivotTransform(BASE, config);
		expect(result.columns.map((c) => c.name)).toEqual(['id', 'city']);
	});
});

// ── unpivotTransform ────────────────────────────────────────────────────────

describe('unpivotTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(unpivotTransform(null, {})).toEqual(EMPTY);
	});

	test('returns variable and value columns', () => {
		const result = unpivotTransform(BASE, {});
		expect(result.columns).toHaveLength(2);
		expect(result.columns[0]).toEqual({ name: 'variable', dtype: 'Utf8', nullable: false });
		expect(result.columns[1]).toEqual({ name: 'value', dtype: 'Any', nullable: true });
	});
});

// ── explodeTransform ────────────────────────────────────────────────────────

describe('explodeTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(explodeTransform(null, {})).toEqual(EMPTY);
	});

	test('removes exploded column when it exists', () => {
		const result = explodeTransform(BASE, { explode_column: 'city' });
		expect(result.columns.map((c) => c.name)).toEqual(['id', 'name', 'age']);
	});

	test('keeps all columns when explode_column not found', () => {
		const result = explodeTransform(BASE, { explode_column: 'nonexistent' });
		expect(result.columns).toHaveLength(4);
	});

	test('keeps all columns when explode_column not specified', () => {
		const result = explodeTransform(BASE, {});
		expect(result.columns).toHaveLength(4);
	});
});

// ── stringTransform ─────────────────────────────────────────────────────────

describe('stringTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(stringTransform(null, {})).toEqual(EMPTY);
	});

	test('returns input when source is missing', () => {
		const result = stringTransform(BASE, {});
		expect(result.columns).toEqual(BASE.columns);
	});

	test('returns input when new_column equals source', () => {
		const result = stringTransform(BASE, { column: 'name', new_column: 'name' });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('returns input when new_column already exists', () => {
		const result = stringTransform(BASE, { column: 'name', new_column: 'age' });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('appends new column for new target name', () => {
		const result = stringTransform(BASE, { column: 'name', new_column: 'name_upper' });
		expect(result.columns).toHaveLength(5);
		expect(result.columns[4].name).toBe('name_upper');
		expect(result.columns[4].dtype).toBe('Any');
	});

	test('falls back to source column when new_column not specified', () => {
		const result = stringTransform(BASE, { column: 'name' });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('uses newColumn (camelCase) as fallback', () => {
		const result = stringTransform(BASE, { column: 'name', newColumn: 'name_lower' });
		expect(result.columns).toHaveLength(5);
		expect(result.columns[4].name).toBe('name_lower');
	});
});

// ── timeseriesTransform ─────────────────────────────────────────────────────

describe('timeseriesTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(timeseriesTransform(null, {})).toEqual(EMPTY);
	});

	test('returns passthrough when new_column or operation_type missing', () => {
		const result = timeseriesTransform(BASE, { column: 'age' });
		expect(result.columns).toEqual(BASE.columns);
		expect(result.row_count).toBe(10);
	});

	test('appends extract column with Int32 dtype', () => {
		const result = timeseriesTransform(BASE, {
			column: 'age',
			new_column: 'year',
			operation_type: 'extract'
		});
		expect(result.columns).toHaveLength(5);
		expect(result.columns[4]).toEqual({ name: 'year', dtype: 'Int32', nullable: false });
	});

	test('appends timestamp column with Int64 dtype', () => {
		const result = timeseriesTransform(BASE, {
			column: 'age',
			new_column: 'ts',
			operation_type: 'timestamp'
		});
		expect(result.columns[4].dtype).toBe('Int64');
	});

	test('appends diff column with Duration dtype', () => {
		const result = timeseriesTransform(BASE, {
			column: 'age',
			new_column: 'delta',
			operation_type: 'diff'
		});
		expect(result.columns[4].dtype).toBe('Duration');
	});

	test('uses source column dtype for other operations', () => {
		const input = schema([{ name: 'ts', dtype: 'Datetime' }]);
		const result = timeseriesTransform(input, {
			column: 'ts',
			new_column: 'shifted',
			operation_type: 'shift'
		});
		expect(result.columns[1].dtype).toBe('Datetime');
	});

	test('overwrites existing column at same position', () => {
		const input = schema([
			{ name: 'ts', dtype: 'Datetime' },
			{ name: 'year', dtype: 'Utf8' }
		]);
		const result = timeseriesTransform(input, {
			column: 'ts',
			new_column: 'year',
			operation_type: 'extract'
		});
		expect(result.columns).toHaveLength(2);
		expect(result.columns[1].dtype).toBe('Int32');
	});

	test('uses source column dtype for truncate operation', () => {
		const schema: Schema = {
			columns: [{ name: 'event_date', dtype: 'Datetime', nullable: false }],
			row_count: 3
		};
		const result = timeseriesTransform(schema, {
			column: 'event_date',
			operation_type: 'truncate',
			new_column: 'truncated',
			unit: 'days'
		});
		expect(result.columns).toHaveLength(2);
		expect(result.columns[1]).toEqual({ name: 'truncated', dtype: 'Datetime', nullable: false });
	});

	test('uses source column dtype for round operation', () => {
		const schema: Schema = {
			columns: [{ name: 'event_date', dtype: 'Datetime', nullable: false }],
			row_count: 3
		};
		const result = timeseriesTransform(schema, {
			column: 'event_date',
			operation_type: 'round',
			new_column: 'rounded',
			unit: 'hours'
		});
		expect(result.columns).toHaveLength(2);
		expect(result.columns[1]).toEqual({ name: 'rounded', dtype: 'Datetime', nullable: false });
	});
});

// ── nullCountTransform ──────────────────────────────────────────────────────

describe('nullCountTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(nullCountTransform(null, {})).toEqual(EMPTY);
	});

	test('transforms each column name to _null_count suffix', () => {
		const result = nullCountTransform(BASE, {});
		expect(result.columns.map((c) => c.name)).toEqual([
			'id_null_count',
			'name_null_count',
			'age_null_count',
			'city_null_count'
		]);
		expect(result.columns.every((c) => c.dtype === 'UInt32')).toBe(true);
		expect(result.columns.every((c) => !c.nullable)).toBe(true);
	});
});

// ── valueCountsTransform ────────────────────────────────────────────────────

describe('valueCountsTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(valueCountsTransform(null, {})).toEqual(EMPTY);
	});

	test('produces value and count columns', () => {
		const result = valueCountsTransform(BASE, {});
		expect(result.columns).toEqual([
			{ name: 'value', dtype: 'Any', nullable: false },
			{ name: 'count', dtype: 'UInt32', nullable: false }
		]);
	});
});

// ── expressionTransform ─────────────────────────────────────────────────────

describe('expressionTransform', () => {
	test('returns EMPTY for null input', () => {
		expect(expressionTransform(null, {})).toEqual(EMPTY);
	});

	test('returns input when expression or column_name missing', () => {
		const result = expressionTransform(BASE, { expression: 'col("x")' });
		expect(result.columns).toEqual(BASE.columns);
	});

	test('returns input when column_name already exists', () => {
		const result = expressionTransform(BASE, {
			expression: 'col("x")',
			column_name: 'id'
		});
		expect(result.columns).toEqual(BASE.columns);
	});

	test('appends new column for novel column_name', () => {
		const result = expressionTransform(BASE, {
			expression: 'col("x") + 1',
			column_name: 'result'
		});
		expect(result.columns).toHaveLength(5);
		expect(result.columns[4]).toEqual({ name: 'result', dtype: 'Any', nullable: true });
	});

	test('uses target_column as fallback', () => {
		const result = expressionTransform(BASE, {
			expression: 'col("x")',
			target_column: 'computed'
		});
		expect(result.columns[4].name).toBe('computed');
	});
});

// ── joinTransform ───────────────────────────────────────────────────────────

describe('joinTransform', () => {
	const RIGHT = schema([
		{ name: 'id', dtype: 'Int64' },
		{ name: 'email', dtype: 'Utf8' }
	]);

	test('returns right schema when left is null', () => {
		const result = joinTransform(null, { how: 'inner' }, RIGHT);
		expect(result.columns).toEqual(RIGHT.columns);
	});

	test('returns EMPTY when both null', () => {
		expect(joinTransform(null, { how: 'inner' }, null)).toEqual(EMPTY);
	});

	test('inner join produces only overlapping columns', () => {
		const result = joinTransform(BASE, { how: 'inner' }, RIGHT);
		expect(result.columns.map((c) => c.name)).toEqual(['id']);
	});

	test('inner join with right_columns appends non-overlapping', () => {
		const result = joinTransform(BASE, { how: 'inner', right_columns: ['email'] }, RIGHT);
		expect(result.columns.map((c) => c.name)).toContain('email_right');
	});

	test('left join keeps all left columns plus right non-overlapping', () => {
		const result = joinTransform(BASE, { how: 'left' }, RIGHT);
		expect(result.columns.map((c) => c.name)).toContain('id');
		expect(result.columns.map((c) => c.name)).toContain('email_right');
	});

	test('right join keeps all right columns', () => {
		const result = joinTransform(BASE, { how: 'right' }, RIGHT);
		expect(result.columns.map((c) => c.name)).toContain('id');
		expect(result.columns.map((c) => c.name)).toContain('email');
	});

	test('outer join merges both schemas', () => {
		const result = joinTransform(BASE, { how: 'outer' }, RIGHT);
		const names = result.columns.map((c) => c.name);
		expect(names).toContain('id');
		expect(names).toContain('name');
		expect(names).toContain('email_right');
	});

	test('cross join concatenates all columns', () => {
		const left = schema([{ name: 'a', dtype: 'Int64' }]);
		const right = schema([{ name: 'b', dtype: 'Utf8' }]);
		const result = joinTransform(left, { how: 'cross' }, right);
		expect(result.columns.map((c) => c.name)).toEqual(['a', 'b']);
	});

	test('uses custom suffix', () => {
		const result = joinTransform(BASE, { how: 'left', suffix: '_r' }, RIGHT);
		expect(result.columns.map((c) => c.name)).toContain('email_r');
	});

	test('defaults to inner join for unknown how', () => {
		const result = joinTransform(BASE, { how: 'unknown' }, RIGHT);
		expect(result.columns.map((c) => c.name)).toEqual(['id']);
	});
});

// ── unionByNameTransform ────────────────────────────────────────────────────

describe('unionByNameTransform', () => {
	test('returns empty schema for null input', () => {
		expect(unionByNameTransform(null, {}, [])).toEqual(EMPTY);
	});

	test('merges columns from multiple schemas with allow_missing', () => {
		const other = schema([
			{ name: 'id', dtype: 'Int64' },
			{ name: 'extra', dtype: 'Utf8' }
		]);
		const result = unionByNameTransform(BASE, { allow_missing: true }, [other]);
		const names = result.columns.map((c) => c.name);
		expect(names).toContain('id');
		expect(names).toContain('name');
		expect(names).toContain('extra');
	});

	test('with allow_missing=false returns input when columns differ', () => {
		const other = schema([
			{ name: 'id', dtype: 'Int64' },
			{ name: 'extra', dtype: 'Utf8' }
		]);
		const result = unionByNameTransform(BASE, { allow_missing: false }, [other]);
		expect(result.columns).toEqual(BASE.columns);
	});

	test('with allow_missing=false returns merged when columns match', () => {
		const same = schema([
			{ name: 'id', dtype: 'Int64' },
			{ name: 'name', dtype: 'Utf8' },
			{ name: 'age', dtype: 'Int64' },
			{ name: 'city', dtype: 'Utf8', nullable: false }
		]);
		const result = unionByNameTransform(BASE, { allow_missing: false }, [same]);
		expect(result.columns.map((c) => c.name)).toEqual(['id', 'name', 'age', 'city']);
	});

	test('defaults allow_missing to true', () => {
		const other = schema([{ name: 'new_col', dtype: 'Float64' }]);
		const result = unionByNameTransform(BASE, {}, [other]);
		expect(result.columns.map((c) => c.name)).toContain('new_col');
	});
});

// ── getStepTransform ────────────────────────────────────────────────────────

describe('getStepTransform', () => {
	test('returns passthrough for plot_ prefixed steps', () => {
		const transform = getStepTransform({ id: '1', type: 'plot_bar', config: {} });
		const result = transform(BASE, {});
		expect(result).toEqual(BASE);
	});

	test('returns correct transform for known step types', () => {
		const selectFn = getStepTransform({ id: '1', type: 'select', config: {} });
		expect(selectFn).toBe(selectTransform);
	});

	test('returns passthrough for unknown step types', () => {
		const transform = getStepTransform({ id: '1', type: 'custom_unknown', config: {} });
		const result = transform(BASE, {});
		expect(result).toEqual(BASE);
	});

	test('filter step clears row_count', () => {
		const transform = getStepTransform({ id: '1', type: 'filter', config: {} });
		const result = transform(BASE, {});
		expect(result.row_count).toBeNull();
		expect(result.columns).toEqual(BASE.columns);
	});

	test('sort step is passthrough', () => {
		const transform = getStepTransform({ id: '1', type: 'sort', config: {} });
		const result = transform(BASE, {});
		expect(result).toEqual(BASE);
	});

	test('deduplicate clears row_count', () => {
		const transform = getStepTransform({ id: '1', type: 'deduplicate', config: {} });
		const result = transform(BASE, {});
		expect(result.row_count).toBeNull();
	});

	test('sample clears row_count', () => {
		const transform = getStepTransform({ id: '1', type: 'sample', config: {} });
		const result = transform(BASE, {});
		expect(result.row_count).toBeNull();
	});

	test('limit clears row_count', () => {
		const transform = getStepTransform({ id: '1', type: 'limit', config: {} });
		const result = transform(BASE, {});
		expect(result.row_count).toBeNull();
	});
});
