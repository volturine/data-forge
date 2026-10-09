import type { ComputeWorkerStatusResponse } from '$lib/types/compute';
import {
	connectComputeWorkersStream,
	shutdownAnalysisComputeWorker as shutdownAnalysisComputeWorkerApi,
	shutdownComputeWorkerByIdentity
} from '$lib/api/compute';
import { ReconnectionManager } from './reconnection-manager';
import { SvelteSet } from 'svelte/reactivity';
import { computeWorkerIdentityKey } from '$lib/representations/compute-worker';

const RECONNECT_DELAY_MS = 1_000;
const SNAPSHOT_REFRESH_COOLDOWN_MS = 15_000;

export type ComputeWorkersConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export class ComputeWorkersStore {
	computeWorkers = $state.raw<ComputeWorkerStatusResponse[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	status = $state<ComputeWorkersConnectionStatus>('disconnected');
	private shuttingDown = new SvelteSet<string>();

	private connection: { close: () => void } | null = null;
	private snapshotConnection: { close: () => void } | null = null;
	private snapshotGeneration = 0;
	private snapshotRequested = false;
	private lastSnapshotAt: number | null = null;
	private reconnect = new ReconnectionManager(RECONNECT_DELAY_MS);
	private shouldReconnect = false;
	private subscribers = 0;
	private holdUntilEmpty = false;

	count = $derived(this.computeWorkers.length);

	loadSnapshotOnce(): void {
		if (this.shouldReconnect || this.snapshotConnection || this.snapshotRequested) return;
		this.snapshotRequested = true;
		this.openSnapshotRequest();
	}

	refreshSnapshot(): void {
		if (this.shouldReconnect || this.snapshotConnection) return;
		if (
			this.lastSnapshotAt !== null &&
			Date.now() - this.lastSnapshotAt < SNAPSHOT_REFRESH_COOLDOWN_MS
		)
			return;
		this.openSnapshotRequest();
	}

	private openSnapshotRequest(): void {
		const generation = ++this.snapshotGeneration;
		let receivedSnapshot = false;
		let failed = false;
		let connection: { close: () => void } | null = null;
		this.loading = true;
		this.error = null;
		this.status = 'connecting';

		const clearConnection = () => {
			if (this.snapshotGeneration === generation && this.snapshotConnection === connection) {
				this.snapshotConnection = null;
			}
		};

		connection = connectComputeWorkersStream({
			onSnapshot: (computeWorkers) => {
				if (this.snapshotGeneration !== generation) {
					connection?.close();
					return;
				}
				receivedSnapshot = true;
				this.applySnapshot(computeWorkers);
				connection?.close();
				clearConnection();
			},
			onError: (message) => {
				if (this.snapshotGeneration !== generation) return;
				failed = true;
				this.snapshotRequested = false;
				this.loading = false;
				this.error = message;
				this.status = 'error';
				connection?.close();
				clearConnection();
			},
			onClose: () => {
				clearConnection();
				if (this.snapshotGeneration !== generation || receivedSnapshot || failed) return;
				this.snapshotRequested = false;
				this.loading = false;
				this.status = 'disconnected';
			}
		});
		this.snapshotConnection = connection;
	}

	startStream(): void {
		this.cancelSnapshot();
		this.subscribers++;
		this.holdUntilEmpty = false;
		if (this.shouldReconnect) return;
		this.shouldReconnect = true;
		this.openConnection(true);
	}

	stopStream(): void {
		this.subscribers = Math.max(0, this.subscribers - 1);
		if (this.subscribers > 0) return;
		if (this.snapshotConnection) {
			this.cancelSnapshot();
			this.loading = false;
			this.status = this.computeWorkers.length > 0 ? 'connected' : 'disconnected';
			return;
		}
		if (this.computeWorkers.length > 0 || this.loading || this.connection) {
			this.holdUntilEmpty = true;
			this.shouldReconnect = true;
			return;
		}
		this.holdUntilEmpty = false;
		this.shouldReconnect = false;
		this.clearReconnectTimer();
		this.connection = null;
		this.computeWorkers = [];
		this.loading = false;
		this.error = null;
		this.status = 'disconnected';
	}

	/**
	 * Shut down a compute worker via the API. Backend cancels any active job first,
	 * then stops the container. 404 means already gone (race with reaper).
	 */
	async shutdownComputeWorker(computeWorker: ComputeWorkerStatusResponse): Promise<void> {
		const key = computeWorkerIdentityKey(computeWorker);
		this.shuttingDown.add(key);
		await shutdownComputeWorkerByIdentity(
			computeWorker.scope ?? 'analysis_interactive',
			computeWorker.resource_id
		).match(
			() => {
				this.computeWorkers = this.computeWorkers.filter(
					(item) => computeWorkerIdentityKey(item) !== key
				);
				this.error = null;
			},
			(err) => {
				this.shuttingDown.delete(key);
				// Already reaped / never existed — treat as success for the UI.
				if (err.status === 404) {
					this.computeWorkers = this.computeWorkers.filter(
						(item) => computeWorkerIdentityKey(item) !== key
					);
					this.error = null;
					return;
				}
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	async shutdownAnalysisComputeWorker(analysisId: string): Promise<void> {
		await shutdownAnalysisComputeWorkerApi(analysisId).match(
			() => {
				this.error = null;
			},
			(err) => {
				if (err.status === 404) {
					this.error = null;
					return;
				}
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	reset(): void {
		this.cancelSnapshot();
		this.snapshotRequested = false;
		this.lastSnapshotAt = null;
		this.holdUntilEmpty = false;
		this.shouldReconnect = false;
		this.subscribers = 0;
		this.clearReconnectTimer();
		this.connection?.close();
		this.connection = null;
		this.computeWorkers = [];
		this.shuttingDown.clear();
		this.loading = false;
		this.error = null;
		this.status = 'disconnected';
	}

	get isStreaming(): boolean {
		return this.shouldReconnect;
	}

	private openConnection(isInitial: boolean): void {
		if (this.connection) return;

		this.clearReconnectTimer();
		this.error = null;
		this.status = 'connecting';
		if (isInitial && this.computeWorkers.length === 0) {
			this.loading = true;
		}

		this.connection = connectComputeWorkersStream({
			onSnapshot: (computeWorkers) => this.applySnapshot(computeWorkers),
			onError: (message) => {
				if (/not authenticated/i.test(message)) {
					this.holdUntilEmpty = false;
					this.shouldReconnect = false;
					this.snapshotRequested = false;
					this.clearReconnectTimer();
				}
				this.loading = false;
				this.error = message;
				this.status = 'error';
			},
			onClose: () => {
				this.connection = null;
				if (!this.shouldReconnect && !this.holdUntilEmpty) {
					this.loading = false;
					this.status = 'disconnected';
					return;
				}
				this.scheduleReconnect();
			}
		});
	}

	private applySnapshot(computeWorkers: ComputeWorkerStatusResponse[]): void {
		this.snapshotRequested = true;
		this.lastSnapshotAt = Date.now();
		for (const key of this.shuttingDown) {
			if (computeWorkers.some((computeWorker) => computeWorkerIdentityKey(computeWorker) === key))
				continue;
			this.shuttingDown.delete(key);
		}
		this.computeWorkers = computeWorkers.filter(
			(computeWorker) => !this.shuttingDown.has(computeWorkerIdentityKey(computeWorker))
		);
		this.loading = false;
		this.error = null;
		this.status = 'connected';
		if (this.holdUntilEmpty && this.subscribers === 0 && this.computeWorkers.length === 0) {
			this.holdUntilEmpty = false;
			this.shouldReconnect = false;
			this.clearReconnectTimer();
			this.connection?.close();
		}
	}

	private cancelSnapshot(): void {
		this.snapshotGeneration++;
		const connection = this.snapshotConnection;
		this.snapshotConnection = null;
		connection?.close();
	}

	private scheduleReconnect(): void {
		this.reconnect.schedule(() => {
			if (!this.shouldReconnect) return;
			this.openConnection(false);
		});
	}

	private clearReconnectTimer(): void {
		this.reconnect.clear();
	}
}

export const computeWorkersStore = new ComputeWorkersStore();
