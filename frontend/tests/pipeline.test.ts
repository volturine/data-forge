import { describe, it, expect } from 'vitest';
import { applySteps } from '../src/lib/utils/pipeline';
import type { PipelineStep } from '../src/lib/types/analysis';

describe('applySteps', () => {
	it('drops disabled steps and relinks dependencies', () => {
		const steps: PipelineStep[] = [
			{
				id: 's1',
				type: 'filter',
				config: {},
				depends_on: []
			},
			{
				id: 's2',
				type: 'notification',
				config: {},
				depends_on: ['s1'],
				is_applied: false
			},
			{
				id: 's3',
				type: 'select',
				config: {},
				depends_on: ['s2']
			}
		];

		const applied = applySteps(steps);

		expect(applied.map((step) => step.id)).toEqual(['s1', 's3']);
		expect(applied[1].depends_on).toEqual(['s1']);
	});

	it('handles empty applied steps', () => {
		const steps: PipelineStep[] = [
			{
				id: 's1',
				type: 'filter',
				config: {},
				depends_on: [],
				is_applied: false
			}
		];

		const applied = applySteps(steps);
		expect(applied).toEqual([]);
	});
});
