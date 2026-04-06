import { describe, test, expect } from 'vitest';
import type { Schema, Column } from './schema';
import {
	emptySchema,
	getColumn,
	hasColumn,
	columnNames,
	unionByName,
	intersectSchemas,
	leftJoinSchema,
	rightJoinSchema,
	outerJoinSchema,
	crossJoinSchema
} from './schema';

function col(name: string, dtype = 'String', nullable = false): Column {
	return { name, dtype, nullable };
}

function schema(columns: Column[], count: number | null = null): Schema {
	return { columns, row_count: count };
}

describe('emptySchema', () => {
	test('returns schema with no columns and null row_count', () => {
		const s = emptySchema();
		expect(s.columns).toEqual([]);
		expect(s.row_count).toBeNull();
	});

	test('each call returns a fresh object', () => {
		const a = emptySchema();
		const b = emptySchema();
		expect(a).not.toBe(b);
		a.columns.push(col('x'));
		expect(b.columns).toHaveLength(0);
	});
});

describe('getColumn', () => {
	const s = schema([col('id', 'Int64'), col('name', 'String')]);

	test('returns column by name', () => {
		const c = getColumn(s, 'id');
		expect(c).toEqual({ name: 'id', dtype: 'Int64', nullable: false });
	});

	test('returns null for missing column', () => {
		expect(getColumn(s, 'missing')).toBeNull();
	});

	test('returns null for null schema', () => {
		expect(getColumn(null, 'id')).toBeNull();
	});

	test('is case-sensitive', () => {
		expect(getColumn(s, 'ID')).toBeNull();
		expect(getColumn(s, 'Name')).toBeNull();
	});
});

describe('hasColumn', () => {
	const s = schema([col('a'), col('b')]);

	test('returns true for existing column', () => {
		expect(hasColumn(s, 'a')).toBe(true);
	});

	test('returns false for missing column', () => {
		expect(hasColumn(s, 'z')).toBe(false);
	});

	test('returns false for null schema', () => {
		expect(hasColumn(null, 'a')).toBe(false);
	});

	test('returns false for empty schema', () => {
		expect(hasColumn(emptySchema(), 'a')).toBe(false);
	});
});

describe('columnNames', () => {
	test('returns all column names in order', () => {
		const s = schema([col('x'), col('y'), col('z')]);
		expect(columnNames(s)).toEqual(['x', 'y', 'z']);
	});

	test('returns empty array for null schema', () => {
		expect(columnNames(null)).toEqual([]);
	});

	test('returns empty array for empty schema', () => {
		expect(columnNames(emptySchema())).toEqual([]);
	});
});

describe('unionByName', () => {
	test('merges columns from multiple schemas', () => {
		const a = schema([col('id', 'Int64'), col('name', 'String')]);
		const b = schema([col('name', 'String'), col('age', 'Int64')]);
		const result = unionByName([a, b]);

		expect(columnNames(result)).toEqual(['id', 'name', 'age']);
	});

	test('first schema dtype wins for overlapping columns', () => {
		const a = schema([col('x', 'Int64')]);
		const b = schema([col('x', 'Float64')]);
		const result = unionByName([a, b]);

		expect(getColumn(result, 'x')?.dtype).toBe('Int64');
	});

	test('nullable is OR of overlapping columns', () => {
		const a = schema([col('x', 'Int64', false)]);
		const b = schema([col('x', 'Int64', true)]);

		expect(unionByName([a, b]).columns[0].nullable).toBe(true);
		expect(unionByName([b, a]).columns[0].nullable).toBe(true);
	});

	test('empty input returns empty schema', () => {
		const result = unionByName([]);
		expect(result.columns).toEqual([]);
		expect(result.row_count).toBeNull();
	});

	test('single schema is identity', () => {
		const s = schema([col('a', 'Int64'), col('b', 'String')]);
		const result = unionByName([s]);
		expect(columnNames(result)).toEqual(['a', 'b']);
	});

	test('three-way union preserves all unique columns', () => {
		const a = schema([col('x')]);
		const b = schema([col('y')]);
		const c = schema([col('z')]);
		expect(columnNames(unionByName([a, b, c]))).toEqual(['x', 'y', 'z']);
	});
});

describe('intersectSchemas', () => {
	const left = schema([col('id', 'Int64'), col('name', 'String'), col('age', 'Int64')]);
	const right = schema([col('id', 'Int64'), col('name', 'String', true), col('email', 'String')]);

	test('keeps only columns present in both', () => {
		const result = intersectSchemas(left, right);
		expect(columnNames(result)).toEqual(['id', 'name']);
	});

	test('nullable is OR of both sides', () => {
		const result = intersectSchemas(left, right);
		expect(getColumn(result, 'name')?.nullable).toBe(true);
		expect(getColumn(result, 'id')?.nullable).toBe(false);
	});

	test('returns empty when no overlap', () => {
		const a = schema([col('x')]);
		const b = schema([col('y')]);
		expect(intersectSchemas(a, b).columns).toEqual([]);
	});

	test('with null right returns empty', () => {
		expect(intersectSchemas(left, null).columns).toEqual([]);
	});

	test('rightColumns adds non-overlapping right cols with suffix', () => {
		const result = intersectSchemas(left, right, '_r', ['email']);
		expect(columnNames(result)).toEqual(['id', 'name', 'email_r']);
		expect(getColumn(result, 'email_r')?.nullable).toBe(true);
	});

	test('rightColumns filters to only specified columns', () => {
		const result = intersectSchemas(left, right, '', ['email']);
		expect(columnNames(result)).toContain('email');
	});
});

describe('leftJoinSchema', () => {
	const left = schema([col('id', 'Int64'), col('name', 'String')]);
	const right = schema([col('id', 'Int64'), col('score', 'Float64'), col('grade', 'String')]);

	test('keeps all left columns plus non-overlapping right columns', () => {
		const result = leftJoinSchema(left, right);
		expect(columnNames(result)).toEqual(['id', 'name', 'score_right', 'grade_right']);
	});

	test('right columns are nullable (left join may miss)', () => {
		const result = leftJoinSchema(left, right);
		expect(getColumn(result, 'score_right')?.nullable).toBe(true);
		expect(getColumn(result, 'grade_right')?.nullable).toBe(true);
	});

	test('left columns retain original nullability', () => {
		const result = leftJoinSchema(left, right);
		expect(getColumn(result, 'id')?.nullable).toBe(false);
	});

	test('custom suffix', () => {
		const result = leftJoinSchema(left, right, '_r');
		expect(columnNames(result)).toContain('score_r');
	});

	test('null right returns left columns only', () => {
		const result = leftJoinSchema(left, null);
		expect(columnNames(result)).toEqual(['id', 'name']);
	});

	test('rightColumns filters which right columns are included', () => {
		const result = leftJoinSchema(left, right, '_right', ['score']);
		expect(columnNames(result)).toEqual(['id', 'name', 'score_right']);
	});

	test('overlapping columns from right are excluded', () => {
		const result = leftJoinSchema(left, right);
		const names = columnNames(result);
		expect(names.filter((n) => n === 'id')).toHaveLength(1);
	});
});

describe('rightJoinSchema', () => {
	const left = schema([col('id', 'Int64'), col('tag', 'String')]);
	const right = schema([col('id', 'Int64'), col('value', 'Float64')]);

	test('keeps non-overlapping left columns plus all right columns', () => {
		const result = rightJoinSchema(left, right);
		expect(columnNames(result)).toEqual(['tag_left', 'id', 'value']);
	});

	test('left-only columns are nullable and suffixed', () => {
		const result = rightJoinSchema(left, right);
		expect(getColumn(result, 'tag_left')?.nullable).toBe(true);
	});

	test('right columns retain original nullability', () => {
		const result = rightJoinSchema(left, right);
		expect(getColumn(result, 'id')?.nullable).toBe(false);
	});

	test('null left returns right columns only', () => {
		const result = rightJoinSchema(null, right);
		expect(columnNames(result)).toEqual(['id', 'value']);
	});

	test('custom suffix applies to left columns', () => {
		const result = rightJoinSchema(left, right, '_l');
		expect(columnNames(result)).toContain('tag_l');
	});
});

describe('outerJoinSchema', () => {
	const left = schema([col('id', 'Int64'), col('a', 'String')]);
	const right = schema([col('id', 'Int64', true), col('b', 'Float64')]);

	test('includes all columns from both sides', () => {
		const result = outerJoinSchema(left, right);
		expect(columnNames(result)).toEqual(['id', 'a', 'b_other']);
	});

	test('overlapping columns merge nullable (OR)', () => {
		const result = outerJoinSchema(left, right);
		expect(getColumn(result, 'id')?.nullable).toBe(true);
	});

	test('non-overlapping right columns are nullable and suffixed', () => {
		const result = outerJoinSchema(left, right);
		expect(getColumn(result, 'b_other')?.nullable).toBe(true);
	});

	test('null right returns left columns only', () => {
		const result = outerJoinSchema(left, null);
		expect(columnNames(result)).toEqual(['id', 'a']);
	});

	test('custom suffix', () => {
		const result = outerJoinSchema(left, right, '_rhs');
		expect(columnNames(result)).toContain('b_rhs');
	});

	test('rightColumns filters non-overlapping right columns', () => {
		const r = schema([col('id', 'Int64'), col('b', 'Float64'), col('c', 'String')]);
		const result = outerJoinSchema(left, r, '_o', ['b']);
		expect(columnNames(result)).toEqual(['id', 'a', 'b_o']);
	});
});

describe('crossJoinSchema', () => {
	test('concatenates all columns from left and right', () => {
		const left = schema([col('a'), col('b')]);
		const right = schema([col('x'), col('y')]);
		const result = crossJoinSchema(left, right);
		expect(columnNames(result)).toEqual(['a', 'b', 'x', 'y']);
	});

	test('preserves dtypes and nullability', () => {
		const left = schema([col('a', 'Int64', true)]);
		const right = schema([col('b', 'Float64', false)]);
		const result = crossJoinSchema(left, right);
		expect(result.columns[0]).toEqual({ name: 'a', dtype: 'Int64', nullable: true });
		expect(result.columns[1]).toEqual({ name: 'b', dtype: 'Float64', nullable: false });
	});

	test('empty left returns right columns only', () => {
		const result = crossJoinSchema(emptySchema(), schema([col('x')]));
		expect(columnNames(result)).toEqual(['x']);
	});

	test('empty right returns left columns only', () => {
		const result = crossJoinSchema(schema([col('a')]), emptySchema());
		expect(columnNames(result)).toEqual(['a']);
	});

	test('both empty returns empty', () => {
		const result = crossJoinSchema(emptySchema(), emptySchema());
		expect(result.columns).toEqual([]);
	});

	test('row_count is always null', () => {
		const left = schema([col('a')], 10);
		const right = schema([col('b')], 20);
		expect(crossJoinSchema(left, right).row_count).toBeNull();
	});
});
