import { describe, expect, it } from 'vitest';
import { hashPipeline, hashesEqual, isCacheStale } from '$lib/utils/hash';

const steps = [
	{ id: 'step-2', type: 'select', config: { columns: ['name'] }, depends_on: ['step-1'] },
	{
		id: 'step-1',
		type: 'filter',
		config: { column: 'age', operator: '>', value: 20 },
		depends_on: []
	}
];

describe('hash utils', () => {
	it('hashPipeline is deterministic regardless of order', () => {
		const first = hashPipeline(steps);
		const second = hashPipeline([...steps].reverse());
		expect(first).toBe(second);
	});

	it('hashesEqual compares hashes', () => {
		const hash = hashPipeline(steps);
		expect(hashesEqual(hash, hash)).toBe(true);
	});

	it('isCacheStale detects changes', () => {
		const hash = hashPipeline(steps);
		const next = [...steps, { id: 'step-3', type: 'limit', config: { rowLimit: 5 } }];
		expect(isCacheStale(hash, steps)).toBe(false);
		expect(isCacheStale(hash, next)).toBe(true);
	});
});
