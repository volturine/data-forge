import type { EngineRun, ListEngineRunsParams } from '$lib/api/engine-runs';
import { connectEngineRunsStream } from '$lib/api/engine-runs-stream';

const INITIAL_SNAPSHOT_TIMEOUT_MS = 10_000;

export class EngineRunsStreamStore {
	runs = $state<EngineRun[]>([]);
	connected = $state(false);
	error = $state<string | null>(null);

	private connection: { close: () => void } | null = null;
	private snapshotTimeout: ReturnType<typeof setTimeout> | null = null;

	connect(params: ListEngineRunsParams): void {
		this.disconnect();
		this.error = null;
		this.armSnapshotTimeout();
		this.connection = connectEngineRunsStream(params, {
			onSnapshot: (runs) => {
				this.clearSnapshotTimeout();
				this.runs = runs;
				this.connected = true;
			},
			onUpdate: (run) => {
				this.clearSnapshotTimeout();
				this.applyUpdate(run);
			},
			onError: (msg) => {
				this.clearSnapshotTimeout();
				this.error = msg;
			},
			onClose: () => {
				this.clearSnapshotTimeout();
				this.connected = false;
			}
		});
	}

	disconnect(): void {
		this.clearSnapshotTimeout();
		this.connection?.close();
		this.connection = null;
		this.connected = false;
	}

	private applyUpdate(run: EngineRun): void {
		const idx = this.runs.findIndex((r) => r.id === run.id);
		if (idx >= 0) {
			const next = [...this.runs];
			next[idx] = run;
			this.runs = next;
		} else {
			this.runs = [run, ...this.runs].toSorted((a, b) => b.created_at.localeCompare(a.created_at));
		}
	}

	private armSnapshotTimeout(): void {
		this.clearSnapshotTimeout();
		this.snapshotTimeout = setTimeout(() => {
			if (this.connected) return;
			this.error = 'Timed out waiting for engine runs snapshot';
			this.disconnect();
		}, INITIAL_SNAPSHOT_TIMEOUT_MS);
	}

	private clearSnapshotTimeout(): void {
		if (this.snapshotTimeout === null) return;
		clearTimeout(this.snapshotTimeout);
		this.snapshotTimeout = null;
	}
}
