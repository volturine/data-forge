import { describe, it, expect } from 'vitest';
import {
	normalizeColumnType,
	getColumnTypeConfig,
	resolveColumnType,
	getColumnTypeCategory
} from '../src/lib/utils/columnTypes';

describe('columnTypes', () => {
	it('normalizes parameterized types', () => {
		expect(normalizeColumnType("Datetime(time_unit='us', time_zone=None)")).toBe('Datetime');
		expect(normalizeColumnType("Duration(time_unit='us')")).toBe('Duration');
		expect(normalizeColumnType('List(Int64)')).toBe('List');
		expect(normalizeColumnType("Struct({'a': Int64})")).toBe('Struct');
	});

	it('handles aliases and unknowns', () => {
		expect(normalizeColumnType('Utf8')).toBe('String');
		expect(normalizeColumnType('bool')).toBe('Boolean');
		expect(resolveColumnType(null)).toBe('Any');
	});

	it('returns category and config', () => {
		const config = getColumnTypeConfig('Int64');
		expect(config.label).toBe('Int64');
		expect(getColumnTypeCategory('Int64')).toBe('integer');
	});
});
