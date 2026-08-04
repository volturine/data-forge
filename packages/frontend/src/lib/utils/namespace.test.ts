import { describe, test, expect } from 'vitest';
import { isValidNamespace, normalizeNamespace } from './namespace';

describe('normalizeNamespace', () => {
	test('returns valid lowercase name as-is', () => {
		expect(normalizeNamespace('outputs')).toBe('outputs');
		expect(normalizeNamespace('my-namespace')).toBe('my-namespace');
		expect(normalizeNamespace('my_namespace')).toBe('my_namespace');
	});

	test('allows digits', () => {
		expect(normalizeNamespace('ns123')).toBe('ns123');
	});

	test('trims whitespace from valid input', () => {
		expect(normalizeNamespace('  outputs  ')).toBe('outputs');
	});

	test('returns empty string for empty input', () => {
		expect(normalizeNamespace('')).toBe('');
	});

	test('returns empty string for whitespace-only input', () => {
		expect(normalizeNamespace('   ')).toBe('');
	});

	test('returns empty string for input with spaces', () => {
		expect(normalizeNamespace('my namespace')).toBe('');
	});

	test('returns empty string for special characters and uppercase', () => {
		expect(normalizeNamespace('ns@123')).toBe('');
		expect(normalizeNamespace('ns.foo')).toBe('');
		expect(normalizeNamespace('ns/bar')).toBe('');
		expect(normalizeNamespace('MyNamespace')).toBe('');
	});

	test('rejects too-short names', () => {
		expect(normalizeNamespace('ab')).toBe('');
		expect(isValidNamespace('ab')).toBe(false);
	});
});
