import { describe, test, expect } from 'vitest';
import {
	normalizeColumnType,
	getColumnTypeConfig,
	resolveColumnType,
	getColumnTypesByCategory,
	getAllColumnTypes,
	COLUMN_TYPE_REGISTRY
} from './column-types';

// ── normalizeColumnType ─────────────────────────────────────────────────────

describe('normalizeColumnType', () => {
	test('passes through canonical types', () => {
		expect(normalizeColumnType('Int64')).toBe('Int64');
		expect(normalizeColumnType('Float64')).toBe('Float64');
		expect(normalizeColumnType('Boolean')).toBe('Boolean');
	});

	test('normalizes Utf8 to String', () => {
		expect(normalizeColumnType('Utf8')).toBe('String');
	});

	test('normalizes Timestamp to Datetime', () => {
		expect(normalizeColumnType('Timestamp')).toBe('Datetime');
	});

	test('normalizes Array to List', () => {
		expect(normalizeColumnType('Array')).toBe('List');
	});

	test('strips parameterized Polars type suffixes', () => {
		expect(normalizeColumnType("Datetime(time_unit='us', time_zone=None)")).toBe('Datetime');
		expect(normalizeColumnType("Duration(time_unit='us')")).toBe('Duration');
	});

	test('strips complex parameterized types', () => {
		expect(normalizeColumnType('List(Int64)')).toBe('List');
		expect(normalizeColumnType("Struct({'a': Int64, 'b': String})")).toBe('Struct');
	});

	test('normalizes Python shorthand aliases', () => {
		expect(normalizeColumnType('str')).toBe('String');
		expect(normalizeColumnType('int')).toBe('Int64');
		expect(normalizeColumnType('float')).toBe('Float64');
		expect(normalizeColumnType('bool')).toBe('Boolean');
	});

	test('normalizes Unknown variants to Any', () => {
		expect(normalizeColumnType('Unknown')).toBe('Any');
		expect(normalizeColumnType('unknown')).toBe('Any');
	});

	test('returns unrecognized types as-is', () => {
		expect(normalizeColumnType('CustomType')).toBe('CustomType');
	});
});

// ── getColumnTypeConfig ─────────────────────────────────────────────────────

describe('getColumnTypeConfig', () => {
	test('returns config for known type', () => {
		const config = getColumnTypeConfig('Int64');
		expect(config.type).toBe('Int64');
		expect(config.category).toBe('integer');
		expect(config.label).toBe('Int64');
	});

	test('returns config via normalization for Utf8', () => {
		const config = getColumnTypeConfig('Utf8');
		expect(config.canonicalName).toBe('String');
	});

	test('returns config for parameterized type', () => {
		const config = getColumnTypeConfig("Datetime(time_unit='us')");
		expect(config.category).toBe('temporal');
	});

	test('falls back to Any config for unknown type', () => {
		const config = getColumnTypeConfig('TotallyUnknown');
		expect(config.type).toBe('Any');
		expect(config.category).toBe('other');
	});

	test('returns correct category for all base types', () => {
		expect(getColumnTypeConfig('String').category).toBe('string');
		expect(getColumnTypeConfig('Categorical').category).toBe('string');
		expect(getColumnTypeConfig('Int8').category).toBe('integer');
		expect(getColumnTypeConfig('UInt32').category).toBe('integer');
		expect(getColumnTypeConfig('Float32').category).toBe('float');
		expect(getColumnTypeConfig('Date').category).toBe('temporal');
		expect(getColumnTypeConfig('Time').category).toBe('temporal');
		expect(getColumnTypeConfig('Boolean').category).toBe('boolean');
		expect(getColumnTypeConfig('List').category).toBe('complex');
		expect(getColumnTypeConfig('Struct').category).toBe('complex');
		expect(getColumnTypeConfig('Binary').category).toBe('other');
		expect(getColumnTypeConfig('Null').category).toBe('other');
	});
});

// ── resolveColumnType ───────────────────────────────────────────────────────

describe('resolveColumnType', () => {
	test('resolves known type to canonical name', () => {
		expect(resolveColumnType('Int64')).toBe('Int64');
		expect(resolveColumnType('Utf8')).toBe('String');
	});

	test('returns Any for null', () => {
		expect(resolveColumnType(null)).toBe('Any');
	});

	test('returns Any for undefined', () => {
		expect(resolveColumnType(undefined)).toBe('Any');
	});

	test('returns Any for empty string', () => {
		expect(resolveColumnType('')).toBe('Any');
	});

	test('resolves parameterized type', () => {
		expect(resolveColumnType("Datetime(time_unit='us')")).toBe('Datetime');
	});
});

// ── getColumnTypesByCategory ────────────────────────────────────────────────

describe('getColumnTypesByCategory', () => {
	test('returns all expected categories', () => {
		const grouped = getColumnTypesByCategory();
		expect(Object.keys(grouped).sort()).toEqual([
			'boolean',
			'complex',
			'float',
			'integer',
			'other',
			'string',
			'temporal'
		]);
	});

	test('each category contains at least one type', () => {
		const grouped = getColumnTypesByCategory();
		for (const category of Object.values(grouped)) {
			expect(category.length).toBeGreaterThan(0);
		}
	});

	test('does not include duplicate canonical names', () => {
		const grouped = getColumnTypesByCategory();
		const allTypes = Object.values(grouped).flat();
		const canonical = allTypes.map((t) => t.canonicalName);
		expect(new Set(canonical).size).toBe(canonical.length);
	});
});

// ── getAllColumnTypes ────────────────────────────────────────────────────────

describe('getAllColumnTypes', () => {
	test('returns only unique canonical types', () => {
		const types = getAllColumnTypes();
		const names = types.map((t) => t.canonicalName);
		expect(new Set(names).size).toBe(names.length);
	});

	test('includes core types', () => {
		const names = getAllColumnTypes().map((t) => t.canonicalName);
		expect(names).toContain('String');
		expect(names).toContain('Int64');
		expect(names).toContain('Float64');
		expect(names).toContain('Boolean');
		expect(names).toContain('Datetime');
		expect(names).toContain('Any');
	});

	test('excludes alias entries', () => {
		const types = getAllColumnTypes();
		const typeNames = types.map((t) => t.type);
		const utfEntries = typeNames.filter((t) => t === 'Utf8');
		expect(utfEntries.length).toBeLessThanOrEqual(1);
	});
});

// ── COLUMN_TYPE_REGISTRY consistency ────────────────────────────────────────

describe('COLUMN_TYPE_REGISTRY consistency', () => {
	test('every entry has required fields', () => {
		for (const [key, config] of Object.entries(COLUMN_TYPE_REGISTRY)) {
			expect(config.type).toBe(key);
			expect(config.label).toBeTruthy();
			expect(config.canonicalName).toBeTruthy();
			expect(config.category).toBeTruthy();
			expect(config.icon).toBeDefined();
			expect(config.description).toBeTruthy();
			expect(Array.isArray(config.aliases)).toBe(true);
		}
	});
});
