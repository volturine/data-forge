import { describe, expect, it } from 'vitest';

import type { ComputeWorkerRunExecutionEntry } from '$lib/api/compute-worker-runs';
import {
	buildStatusLabel,
	buildStatusTone,
	buildStepStateFromComputeWorkerRunStatus,
	buildStepTypeFromExecutionEntry,
	countComputeWorkerRunSteps,
	computeWorkerRunDisplayKind,
	computeWorkerRunKindLabel,
	computeWorkerRunStatusFilterValue,
	computeWorkerRunStatusToBuildLifecycleStatus
} from './build-stream';

describe('build-stream ownership helpers', () => {
	it('owns build and compute-worker-run status projections', () => {
		expect(buildStatusLabel('running', 'Apply filter')).toBe('Apply filter');
		expect(buildStatusTone('cancelled')).toBe('warning');
		expect(computeWorkerRunStatusToBuildLifecycleStatus('success')).toBe('completed');
		expect(computeWorkerRunStatusFilterValue('completed')).toBe('success');
	});

	it('owns compute-worker-run kind labels', () => {
		expect(computeWorkerRunDisplayKind('raw')).toBe('build');
		expect(computeWorkerRunDisplayKind('ingest')).toBe('build');
		expect(computeWorkerRunKindLabel('row_count')).toBe('Row Count');
		expect(computeWorkerRunKindLabel('download')).toBe('Download');
		expect(computeWorkerRunKindLabel('ingest')).toBe('Build');
	});

	it('owns execution-entry step typing and counting', () => {
		const entries: ComputeWorkerRunExecutionEntry[] = [
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

		expect(countComputeWorkerRunSteps(entries)).toBe(2);
		expect(buildStepTypeFromExecutionEntry(entries[1])).toBe('read');
		expect(buildStepTypeFromExecutionEntry(entries[2])).toBe('filter');
		expect(buildStepStateFromComputeWorkerRunStatus('failed', { isLastStep: true })).toBe('failed');
		expect(buildStepStateFromComputeWorkerRunStatus('success', { isLastStep: true })).toBe(
			'completed'
		);
	});
});
