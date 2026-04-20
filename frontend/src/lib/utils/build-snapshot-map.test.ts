import { describe, test, expect } from 'vitest';
import { buildSnapshotMap } from './build-snapshot-map';
import type { EngineRun } from '$lib/api/engine-runs';

function makeRun(id: string, snapshotId?: unknown): EngineRun {
	return {
		id,
		analysis_id: null,
		datasource_id: 'ds-1',
		kind: 'build',
		status: 'success',
		request_json: {},
		result_json: snapshotId !== undefined ? { snapshot_id: snapshotId } : null,
		error_message: null,
		created_at: '2024-01-01T00:00:00Z',
		completed_at: '2024-01-01T00:01:00Z',
		duration_ms: 60000,
		step_timings: {},
		query_plan: null,
		progress: 100,
		current_step: null,
		triggered_by: null,
		execution_entries: []
	};
}

const SNAPSHOTS = [
	{ snapshot_id: 'snap-a', timestamp_ms: 1000 },
	{ snapshot_id: 'snap-b', timestamp_ms: 2000 },
	{ snapshot_id: '42', timestamp_ms: 3000 }
];

describe('buildSnapshotMap', () => {
	test('returns empty map for empty inputs', () => {
		const map = buildSnapshotMap([], []);
		expect(map.size).toBe(0);
	});

	test('returns empty map when runs have no result_json', () => {
		const runs = [makeRun('run-1'), makeRun('run-2')];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('maps run to snapshot when result_json has matching string snapshot_id', () => {
		const runs = [makeRun('run-1', 'snap-a')];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.get('run-1')).toBe('snap-a');
		expect(map.size).toBe(1);
	});

	test('maps multiple runs to their snapshots', () => {
		const runs = [makeRun('run-1', 'snap-a'), makeRun('run-2', 'snap-b')];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.get('run-1')).toBe('snap-a');
		expect(map.get('run-2')).toBe('snap-b');
		expect(map.size).toBe(2);
	});

	test('ignores runs whose snapshot_id is not in the snapshots set', () => {
		const runs = [makeRun('run-1', 'snap-nonexistent')];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('converts numeric snapshot_id to string when matching', () => {
		const runs = [makeRun('run-1', 42)];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.get('run-1')).toBe('42');
	});

	test('ignores numeric snapshot_id when string version not in snapshots', () => {
		const runs = [makeRun('run-1', 999)];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('ignores empty string snapshot_id', () => {
		const runs = [makeRun('run-1', '')];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('ignores non-string non-number snapshot_id', () => {
		const runs = [makeRun('run-1', { nested: true }), makeRun('run-2', true)];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('ignores null result_json', () => {
		const run = makeRun('run-1');
		run.result_json = null;
		const map = buildSnapshotMap([run], SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('handles result_json with empty object (no snapshot_id key)', () => {
		const run = makeRun('run-1');
		run.result_json = {};
		const map = buildSnapshotMap([run], SNAPSHOTS);
		expect(map.size).toBe(0);
	});

	test('returns a SvelteMap instance', () => {
		const map = buildSnapshotMap([], []);
		expect(map).toBeInstanceOf(Map);
	});

	test('handles mix of matching and non-matching runs', () => {
		const runs = [
			makeRun('run-1', 'snap-a'),
			makeRun('run-2', 'nonexistent'),
			makeRun('run-3', 'snap-b'),
			makeRun('run-4')
		];
		const map = buildSnapshotMap(runs, SNAPSHOTS);
		expect(map.size).toBe(2);
		expect(map.get('run-1')).toBe('snap-a');
		expect(map.get('run-3')).toBe('snap-b');
	});

	test('handles undefined snapshot_id in result_json', () => {
		const run = makeRun('run-1');
		run.result_json = { other_field: 'value' };
		const map = buildSnapshotMap([run], SNAPSHOTS);
		expect(map.size).toBe(0);
	});
});
