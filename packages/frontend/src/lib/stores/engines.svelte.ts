import type { EngineStatusResponse } from '$lib/types/compute';
import {
	connectEnginesStream,
	shutdownAnalysisEngine as shutdownAnalysisEngineApi,
	shutdownEngineByIdentity
} from '$lib/api/compute';
import { ReconnectionManager } from './reconnection-manager';
import { SvelteSet } from 'svelte/reactivity';
import { engineIdentityKey } from '$lib/representations/engine';

const RECONNECT_DELAY_MS = 1_000;
const SNAPSHOT_REFRESH_COOLDOWN_MS = 30_000;

export type EnginesConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export class EnginesStore {
	engines = $state.raw<EngineStatusResponse[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	status = $state<EnginesConnectionStatus>('disconnected');
	private shuttingDown = new SvelteSet<string>();

	private connection: { close: () => void } | null = null;
	private snapshotConnection: { close: () => void } | null = null;
	private snapshotGeneration = 0;
	private snapshotRequested = false;
	private lastSnapshotAt = 0;
	private reconnect = new ReconnectionManager(RECONNECT_DELAY_MS);
	private shouldReconnect = false;
	private subscribers = 0;
	private holdUntilEmpty = false;

	count = $derived(this.engines.length);

	loadSnapshotOnce(): void {
		if (this.shouldReconnect || this.snapshotConnection || this.snapshotRequested) return;
		this.snapshotRequested = true;
		this.openSnapshotRequest();
	}

	refreshSnapshot(): void {
		if (this.shouldReconnect || this.snapshotConnection) return;
		if (Date.now() - this.lastSnapshotAt < SNAPSHOT_REFRESH_COOLDOWN_MS) return;
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

		connection = connectEnginesStream({
			onSnapshot: (engines) => {
				if (this.snapshotGeneration !== generation) {
					connection?.close();
					return;
				}
				receivedSnapshot = true;
				this.applySnapshot(engines);
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
			this.status = this.engines.length > 0 ? 'connected' : 'disconnected';
			return;
		}
		if (this.engines.length > 0 || this.loading || this.connection) {
			this.holdUntilEmpty = true;
			this.shouldReconnect = true;
			return;
		}
		this.holdUntilEmpty = false;
		this.shouldReconnect = false;
		this.clearReconnectTimer();
		this.connection = null;
		this.engines = [];
		this.loading = false;
		this.error = null;
		this.status = 'disconnected';
	}

	/**
	 * Shut down an engine via the API. Backend cancels any active job first,
	 * then stops the container. 404 means already gone (race with reaper).
	 */
	async shutdownEngine(engine: EngineStatusResponse): Promise<void> {
		const key = engineIdentityKey(engine);
		this.shuttingDown.add(key);
		await shutdownEngineByIdentity(
			engine.scope ?? 'analysis_interactive',
			engine.resource_id
		).match(
			() => {
				this.engines = this.engines.filter((item) => engineIdentityKey(item) !== key);
				this.error = null;
			},
			(err) => {
				this.shuttingDown.delete(key);
				// Already reaped / never existed — treat as success for the UI.
				if (err.status === 404) {
					this.engines = this.engines.filter((item) => engineIdentityKey(item) !== key);
					this.error = null;
					return;
				}
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	async shutdownAnalysisEngine(analysisId: string): Promise<void> {
		await shutdownAnalysisEngineApi(analysisId).match(
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
		this.lastSnapshotAt = 0;
		this.holdUntilEmpty = false;
		this.shouldReconnect = false;
		this.subscribers = 0;
		this.clearReconnectTimer();
		this.connection?.close();
		this.connection = null;
		this.engines = [];
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
		if (isInitial && this.engines.length === 0) {
			this.loading = true;
		}

		this.connection = connectEnginesStream({
			onSnapshot: (engines) => this.applySnapshot(engines),
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

	private applySnapshot(engines: EngineStatusResponse[]): void {
		this.snapshotRequested = true;
		this.lastSnapshotAt = Date.now();
		for (const key of this.shuttingDown) {
			if (engines.some((engine) => engineIdentityKey(engine) === key)) continue;
			this.shuttingDown.delete(key);
		}
		this.engines = engines.filter((engine) => !this.shuttingDown.has(engineIdentityKey(engine)));
		this.loading = false;
		this.error = null;
		this.status = 'connected';
		if (this.holdUntilEmpty && this.subscribers === 0 && this.engines.length === 0) {
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

export const enginesStore = new EnginesStore();
