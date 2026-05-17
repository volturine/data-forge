import { describe, test, expect } from 'vitest';
import type { PipelineStep } from '$lib/types/analysis';
import { applySteps } from './pipeline';

function step(overrides: Partial<PipelineStep> = {}): PipelineStep {
	return {
		id: 'step-1',
		type: 'select',
		config: {},
		depends_on: [],
		is_applied: true,
		...overrides
	};
}

describe('applySteps', () => {
	test('returns empty array for empty input', () => {
		expect(applySteps([])).toEqual([]);
	});

	test('returns empty array when all steps are unapplied', () => {
		expect(applySteps([step({ is_applied: false })])).toEqual([]);
	});

	test('returns applied steps unchanged when no filtering needed', () => {
		const steps = [step({ id: 's1', depends_on: [] }), step({ id: 's2', depends_on: ['s1'] })];
		const result = applySteps(steps);
		expect(result).toHaveLength(2);
		expect(result[0].id).toBe('s1');
		expect(result[1].id).toBe('s2');
		expect(result[1].depends_on).toEqual(['s1']);
	});

	test('filters out unapplied steps', () => {
		const steps = [
			step({ id: 's1', depends_on: [] }),
			step({ id: 's2', depends_on: ['s1'], is_applied: false }),
			step({ id: 's3', depends_on: ['s2'] })
		];
		const result = applySteps(steps);
		expect(result).toHaveLength(2);
		expect(result.map((s) => s.id)).toEqual(['s1', 's3']);
	});

	test('relinks depends_on when intermediate step is removed', () => {
		const steps = [
			step({ id: 's1', depends_on: [] }),
			step({ id: 's2', depends_on: ['s1'], is_applied: false }),
			step({ id: 's3', depends_on: ['s2'] })
		];
		const result = applySteps(steps);
		expect(result[1].depends_on).toEqual(['s1']);
	});

	test('relinks through multiple unapplied steps', () => {
		const steps = [
			step({ id: 's1', depends_on: [] }),
			step({ id: 's2', depends_on: ['s1'], is_applied: false }),
			step({ id: 's3', depends_on: ['s2'], is_applied: false }),
			step({ id: 's4', depends_on: ['s3'] })
		];
		const result = applySteps(steps);
		expect(result).toHaveLength(2);
		expect(result[1].id).toBe('s4');
		expect(result[1].depends_on).toEqual(['s1']);
	});

	test('clears depends_on when all ancestors are unapplied', () => {
		const steps = [
			step({ id: 's1', depends_on: [], is_applied: false }),
			step({ id: 's2', depends_on: ['s1'] })
		];
		const result = applySteps(steps);
		expect(result).toHaveLength(1);
		expect(result[0].depends_on).toEqual([]);
	});

	test('preserves step with no depends_on', () => {
		const steps = [step({ id: 's1', depends_on: [] })];
		const result = applySteps(steps);
		expect(result).toHaveLength(1);
		expect(result[0].depends_on).toEqual([]);
	});

	test('handles undefined depends_on', () => {
		const steps = [step({ id: 's1', depends_on: undefined })];
		const result = applySteps(steps);
		expect(result).toHaveLength(1);
		expect(result[0].depends_on).toEqual([]);
	});

	test('handles undefined is_applied as applied', () => {
		const s = { id: 's1', type: 'select', config: {}, depends_on: [] } as PipelineStep;
		const result = applySteps([s]);
		expect(result).toHaveLength(1);
	});

	test('handles is_applied explicitly true', () => {
		const steps = [step({ id: 's1', is_applied: true })];
		const result = applySteps(steps);
		expect(result).toHaveLength(1);
	});

	test('does not mutate input array', () => {
		const steps = [
			step({ id: 's1', depends_on: [] }),
			step({ id: 's2', depends_on: ['s1'], is_applied: false }),
			step({ id: 's3', depends_on: ['s2'] })
		];
		const original = JSON.parse(JSON.stringify(steps));
		applySteps(steps);
		expect(steps).toEqual(original);
	});

	test('handles branch-like topology with unapplied middle', () => {
		const steps = [
			step({ id: 'root', depends_on: [] }),
			step({ id: 'mid', depends_on: ['root'], is_applied: false }),
			step({ id: 'branch-a', depends_on: ['mid'] }),
			step({ id: 'branch-b', depends_on: ['root'] })
		];
		const result = applySteps(steps);
		expect(result).toHaveLength(3);
		const branchA = result.find((s) => s.id === 'branch-a');
		const branchB = result.find((s) => s.id === 'branch-b');
		expect(branchA?.depends_on).toEqual(['root']);
		expect(branchB?.depends_on).toEqual(['root']);
	});

	test('avoids infinite loop on circular depends_on', () => {
		const steps = [
			step({ id: 's1', depends_on: ['s2'], is_applied: false }),
			step({ id: 's2', depends_on: ['s1'], is_applied: false }),
			step({ id: 's3', depends_on: ['s2'] })
		];
		const result = applySteps(steps);
		expect(result).toHaveLength(1);
		expect(result[0].depends_on).toEqual([]);
	});

	test('multi-dependency step only resolves first dependency', () => {
		const steps = [
			step({ id: 'left', depends_on: [] }),
			step({ id: 'right', depends_on: [] }),
			step({ id: 'join', depends_on: ['left', 'right'] })
		];
		const result = applySteps(steps);
		expect(result).toHaveLength(3);
		const join = result.find((s) => s.id === 'join');
		expect(join?.depends_on).toEqual(['left']);
	});

	test('multi-dependency step relinks first dep when it is unapplied', () => {
		const steps = [
			step({ id: 'root', depends_on: [] }),
			step({ id: 'left', depends_on: ['root'], is_applied: false }),
			step({ id: 'right', depends_on: [] }),
			step({ id: 'join', depends_on: ['left', 'right'] })
		];
		const result = applySteps(steps);
		const join = result.find((s) => s.id === 'join');
		expect(join?.depends_on).toEqual(['root']);
	});
});
