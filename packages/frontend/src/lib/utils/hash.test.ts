import { describe, test, expect } from 'vitest';
import { hashPipeline, isCacheStale } from './hash';

describe('hashPipeline', () => {
	test('returns a 16-char hex string', () => {
		const hash = hashPipeline([{ id: 'a', type: 'view', config: {} }]);
		expect(hash).toMatch(/^[0-9a-f]{16}$/);
	});

	test('is deterministic for identical input', () => {
		const steps = [{ id: 'a', type: 'filter', config: { col: 'x' } }];
		expect(hashPipeline(steps)).toBe(hashPipeline(steps));
	});

	test('is order-independent (sorts by id)', () => {
		const a = { id: 'a', type: 'view', config: {} };
		const b = { id: 'b', type: 'limit', config: { n: 10 } };
		expect(hashPipeline([a, b])).toBe(hashPipeline([b, a]));
	});

	test('changes when config changes', () => {
		const base = [{ id: 'a', type: 'limit', config: { n: 10 } }];
		const changed = [{ id: 'a', type: 'limit', config: { n: 20 } }];
		expect(hashPipeline(base)).not.toBe(hashPipeline(changed));
	});

	test('changes when step type changes', () => {
		const a = [{ id: 'a', type: 'view', config: {} }];
		const b = [{ id: 'a', type: 'limit', config: {} }];
		expect(hashPipeline(a)).not.toBe(hashPipeline(b));
	});

	test('sorts config keys for consistent hashing', () => {
		const a = [{ id: 'a', type: 'filter', config: { x: 1, y: 2 } }];
		const b = [{ id: 'a', type: 'filter', config: { y: 2, x: 1 } }];
		expect(hashPipeline(a)).toBe(hashPipeline(b));
	});

	test('handles nested config objects with different key order', () => {
		const a = [{ id: 'a', type: 'x', config: { nested: { b: 2, a: 1 } } }];
		const b = [{ id: 'a', type: 'x', config: { nested: { a: 1, b: 2 } } }];
		expect(hashPipeline(a)).toBe(hashPipeline(b));
	});

	test('handles depends_on by sorting them', () => {
		const a = [{ id: 'a', type: 'x', config: {}, depends_on: ['c', 'b'] }];
		const b = [{ id: 'a', type: 'x', config: {}, depends_on: ['b', 'c'] }];
		expect(hashPipeline(a)).toBe(hashPipeline(b));
	});

	test('treats missing depends_on as empty array', () => {
		const a = [{ id: 'a', type: 'x', config: {} }];
		const b = [{ id: 'a', type: 'x', config: {}, depends_on: [] }];
		expect(hashPipeline(a)).toBe(hashPipeline(b));
	});

	test('handles empty steps array', () => {
		const hash = hashPipeline([]);
		expect(hash).toMatch(/^[0-9a-f]{16}$/);
	});

	test('handles config with arrays', () => {
		const a = [{ id: 'a', type: 'x', config: { cols: ['a', 'b'] } }];
		const b = [{ id: 'a', type: 'x', config: { cols: ['a', 'b'] } }];
		expect(hashPipeline(a)).toBe(hashPipeline(b));
	});

	test('config array order matters', () => {
		const a = [{ id: 'a', type: 'x', config: { cols: ['a', 'b'] } }];
		const b = [{ id: 'a', type: 'x', config: { cols: ['b', 'a'] } }];
		expect(hashPipeline(a)).not.toBe(hashPipeline(b));
	});

	test('handles null config values', () => {
		const hash = hashPipeline([{ id: 'a', type: 'x', config: { val: null } }]);
		expect(hash).toMatch(/^[0-9a-f]{16}$/);
	});
});

describe('isCacheStale', () => {
	test('returns false when hash matches', () => {
		const steps = [{ id: 'a', type: 'view', config: {} }];
		const hash = hashPipeline(steps);
		expect(isCacheStale(hash, steps)).toBe(false);
	});

	test('returns true when steps differ', () => {
		const original = [{ id: 'a', type: 'view', config: {} }];
		const hash = hashPipeline(original);
		const changed = [{ id: 'a', type: 'limit', config: { n: 10 } }];
		expect(isCacheStale(hash, changed)).toBe(true);
	});

	test('returns true for arbitrary hash string', () => {
		const steps = [{ id: 'a', type: 'view', config: {} }];
		expect(isCacheStale('0000000000000000', steps)).toBe(true);
	});
});
