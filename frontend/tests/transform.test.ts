import { describe, expect, it } from 'vitest';
import { emptySchema } from '$lib/types/schema';
import {
	filterTransform,
	selectTransform,
	renameTransform,
	unionByNameTransform,
	joinTransform,
	groupbyTransform
} from '$lib/utils/transform';

const baseSchema = {
	columns: [
		{ name: 'id', dtype: 'Int64', nullable: false },
		{ name: 'name', dtype: 'Utf8', nullable: true },
		{ name: 'age', dtype: 'Int64', nullable: true },
		{ name: 'city', dtype: 'Utf8', nullable: true }
	],
	row_count: 10
};

describe('transform utils', () => {
	it('filterTransform keeps columns when conditions present', () => {
		const result = filterTransform(baseSchema, {
			conditions: [{ column: 'age', operator: '>', value: '30' }]
		});

		expect(result.columns).toHaveLength(4);
	});

	it('selectTransform filters to chosen columns', () => {
		const result = selectTransform(baseSchema, { columns: ['id', 'city'] });

		expect(result.columns.map((col) => col.name)).toEqual(['id', 'city']);
	});

	it('renameTransform renames mapped columns', () => {
		const result = renameTransform(baseSchema, {
			mapping: { name: 'full_name' }
		});

		const names = result.columns.map((col) => col.name);
		expect(names).toContain('full_name');
		expect(names).not.toContain('name');
	});

	it('unionByNameTransform merges schema columns', () => {
		const right = {
			columns: [
				{ name: 'id', dtype: 'Int64', nullable: false },
				{ name: 'state', dtype: 'Utf8', nullable: true }
			],
			row_count: 5
		};
		const result = unionByNameTransform(baseSchema, { sources: ['right'] }, [right]);

		const names = result.columns.map((col) => col.name);
		expect(names).toEqual(['id', 'name', 'age', 'city', 'state']);
	});

	it('joinTransform keeps left columns for left join', () => {
		const right = {
			columns: [
				{ name: 'id', dtype: 'Int64', nullable: false },
				{ name: 'city', dtype: 'Utf8', nullable: true },
				{ name: 'country', dtype: 'Utf8', nullable: true }
			],
			row_count: 12
		};
		const result = joinTransform(
			baseSchema,
			{ how: 'left', left_on: 'id', right_on: 'id', suffix: '_right' },
			right
		);

		const names = result.columns.map((col) => col.name);
		expect(names).toContain('city');
		expect(names).not.toContain('city_right');
		expect(names).toContain('country');
	});

	it('groupbyTransform creates grouped columns and preserves count', () => {
		const result = groupbyTransform(baseSchema, {
			groupBy: ['city'],
			aggregations: [{ column: 'age', agg: 'sum', alias: 'age_total' }]
		});

		const names = result.columns.map((col) => col.name);
		expect(names).toContain('city');
		expect(names).toContain('age_total');
	});

	it('returns empty schema for null input', () => {
		const result = selectTransform(null, { columns: ['id'] });
		expect(result).toEqual(emptySchema());
	});
});
