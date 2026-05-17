import { describe, expect, it } from 'vitest';

import type { EngineRunExecutionEntry } from '$lib/api/engine-runs';
import {
	buildStatusLabel,
	buildStatusTone,
	buildStepStateFromEngineRunStatus,
	buildStepTypeFromExecutionEntry,
	countEngineRunSteps,
	engineRunKindLabel,
	engineRunStatusFilterValue,
	engineRunStatusToActiveBuildStatus
} from './build-stream';

describe('build-stream ownership helpers', () => {
	it('owns build and engine-run status projections', () => {
		expect(buildStatusLabel('running', 'Apply filter')).toBe('Apply filter');
		expect(buildStatusTone('cancelled')).toBe('warning');
		expect(engineRunStatusToActiveBuildStatus('success')).toBe('completed');
		expect(engineRunStatusFilterValue('completed')).toBe('success');
	});

	it('owns engine-run kind labels', () => {
		expect(engineRunKindLabel('row_count')).toBe('Row Count');
		expect(engineRunKindLabel('download')).toBe('Download');
	});

	it('owns execution-entry step typing and counting', () => {
		const entries: EngineRunExecutionEntry[] = [
			{
				key: 'plan',
				label: 'Plan',
				category: 'plan',
				order: 0,
				duration_ms: null,
				share_pct: null,
				optimized_plan: null,
				unoptimized_plan: null,
				metadata: null
			},
			{
				key: 'read',
				label: 'Read',
				category: 'read',
				order: 1,
				duration_ms: 12,
				share_pct: 5,
				optimized_plan: null,
				unoptimized_plan: null,
				metadata: null
			},
			{
				key: 'step',
				label: 'Filter',
				category: 'step',
				order: 2,
				duration_ms: 20,
				share_pct: 10,
				optimized_plan: null,
				unoptimized_plan: null,
				metadata: { step_type: 'filter' }
			}
		];

		expect(countEngineRunSteps(entries)).toBe(2);
		expect(buildStepTypeFromExecutionEntry(entries[1])).toBe('read');
		expect(buildStepTypeFromExecutionEntry(entries[2])).toBe('filter');
		expect(buildStepStateFromEngineRunStatus('failed', { isLastStep: true })).toBe('failed');
		expect(buildStepStateFromEngineRunStatus('success', { isLastStep: true })).toBe('completed');
	});
});
