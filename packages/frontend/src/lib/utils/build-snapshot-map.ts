import { SvelteMap } from 'svelte/reactivity';

type SnapshotRef = { snapshot_id: string; timestamp_ms: number };

type SnapshotRun = {
	result_json: Record<string, unknown> | null | undefined;
	id?: string;
	build_id?: string;
};

function runId(run: SnapshotRun): string | null {
	if (typeof run.build_id === 'string' && run.build_id.length > 0) return run.build_id;
	if (typeof run.id === 'string' && run.id.length > 0) return run.id;
	return null;
}

export function buildSnapshotMap<T extends SnapshotRun>(
	runs: T[],
	snapshots: SnapshotRef[]
): SvelteMap<string, string> {
	const snapshotIds = new Set(snapshots.map((snap) => snap.snapshot_id));
	const map = new SvelteMap<string, string>();
	for (const run of runs) {
		const id = runId(run);
		if (!id) continue;
		const direct = run.result_json?.snapshot_id;
		if (typeof direct === 'string' && direct.length > 0 && snapshotIds.has(direct)) {
			map.set(id, direct);
		} else if (typeof direct === 'number' && snapshotIds.has(String(direct))) {
			map.set(id, String(direct));
		}
	}
	return map;
}
