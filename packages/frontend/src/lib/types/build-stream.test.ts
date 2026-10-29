import { describe, expect, it } from 'vitest';

import {
	buildStatusLabel,
	buildStatusTone,
	computeWorkerRunDisplayKind,
	computeWorkerRunKindLabel
} from './build-stream';

describe('build-stream ownership helpers', () => {
	it('owns build status projections', () => {
		expect(buildStatusLabel('running', 'Apply filter')).toBe('Apply filter');
		expect(buildStatusTone('cancelled')).toBe('warning');
	});

	it('owns compute-worker-run kind labels', () => {
		expect(computeWorkerRunDisplayKind('raw')).toBe('build');
		expect(computeWorkerRunDisplayKind('ingest')).toBe('build');
		expect(computeWorkerRunKindLabel('row_count')).toBe('Row Count');
		expect(computeWorkerRunKindLabel('download')).toBe('Download');
		expect(computeWorkerRunKindLabel('ingest')).toBe('Build');
	});
});
