import { SvelteMap } from 'svelte/reactivity';
import type { EngineRun } from '$lib/api/engine-runs';

type SnapshotRef = { snapshot_id: string; timestamp_ms: number };

export function buildSnapshotMap(
	runs: EngineRun[],
	snapshots: SnapshotRef[]
): SvelteMap<string, string> {
	const snapshotIds = new Set(snapshots.map((snap) => snap.snapshot_id));
	const map = new SvelteMap<string, string>();
	for (const run of runs) {
		const result = run.result_json ?? {};
		const direct = result.snapshot_id;
		if (typeof direct === 'string' && direct.length > 0 && snapshotIds.has(direct)) {
			map.set(run.id, direct);
			continue;
		}
		if (typeof direct === 'number') {
			const id = String(direct);
			if (snapshotIds.has(id)) {
				map.set(run.id, id);
			}
		}
	}
	return map;
}
