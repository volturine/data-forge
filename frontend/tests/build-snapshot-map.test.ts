import { describe, expect, it } from 'vitest';
import type { EngineRun } from '$lib/api/engine-runs';
import { buildSnapshotMap } from '$lib/utils/build-snapshot-map';

const makeRun = (overrides: Partial<EngineRun> = {}): EngineRun => ({
	id: 'run-1',
	analysis_id: null,
	datasource_id: 'ds-1',
	kind: 'datasource_update',
	status: 'success',
	request_json: {},
	result_json: null,
	error_message: null,
	created_at: '2024-01-01T00:00:00.000Z',
	completed_at: null,
	duration_ms: null,
	step_timings: {},
	query_plan: null,
	progress: 1,
	current_step: null,
	triggered_by: null,
	...overrides
});

describe('buildSnapshotMap', () => {
	it('maps only existing snapshot ids from run results', () => {
		const runs = [
			makeRun({ id: 'run-1', result_json: { snapshot_id: '100' } }),
			makeRun({ id: 'run-2', result_json: { snapshot_id: 'missing' } }),
			makeRun({ id: 'run-3', result_json: { snapshot_id: 200 } })
		];
		const snapshots = [
			{ snapshot_id: '100', timestamp_ms: 1 },
			{ snapshot_id: '200', timestamp_ms: 2 }
		];
		const map = buildSnapshotMap(runs, snapshots);
		expect(map.get('run-1')).toBe('100');
		expect(map.get('run-3')).toBe('200');
		expect(map.has('run-2')).toBe(false);
	});

	it('does not map runs without a direct snapshot id', () => {
		const runs = [makeRun({ id: 'run-1', result_json: {} })];
		const snapshots = [{ snapshot_id: '100', timestamp_ms: 1 }];
		const map = buildSnapshotMap(runs, snapshots);
		expect(map.size).toBe(0);
	});
});
