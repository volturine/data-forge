import type { EngineStatusResponse } from '$lib/types/compute';
import { connectEnginesStream, shutdownEngine as shutdownEngineApi } from '$lib/api/compute';

const RECONNECT_DELAY_MS = 1_000;

export type EnginesConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export class EnginesStore {
	engines = $state<EngineStatusResponse[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	status = $state<EnginesConnectionStatus>('disconnected');

	private connection: { close: () => void } | null = null;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private shouldReconnect = false;
	private subscribers = 0;

	count = $derived(this.engines.length);

	startStream(): void {
		this.subscribers++;
		if (this.shouldReconnect) return;
		this.shouldReconnect = true;
		this.openConnection(true);
	}

	stopStream(): void {
		this.subscribers = Math.max(0, this.subscribers - 1);
		if (this.subscribers > 0) return;
		this.shouldReconnect = false;
		this.clearReconnectTimer();
		this.connection?.close();
		this.connection = null;
		this.loading = false;
		this.status = 'disconnected';
	}

	async shutdownEngine(analysisId: string): Promise<void> {
		await shutdownEngineApi(analysisId).match(
			() => {
				this.engines = this.engines.filter((engine) => engine.analysis_id !== analysisId);
			},
			(err) => {
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	reset(): void {
		this.shouldReconnect = false;
		this.subscribers = 0;
		this.clearReconnectTimer();
		this.connection?.close();
		this.connection = null;
		this.engines = [];
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
			onSnapshot: (engines) => {
				this.engines = engines;
				this.loading = false;
				this.error = null;
				this.status = 'connected';
			},
			onError: (message) => {
				this.loading = false;
				this.error = message;
				this.status = 'error';
			},
			onClose: () => {
				this.connection = null;
				if (!this.shouldReconnect) {
					this.loading = false;
					this.status = 'disconnected';
					return;
				}
				this.scheduleReconnect();
			}
		});
	}

	private scheduleReconnect(): void {
		if (this.reconnectTimer !== null) return;
		this.reconnectTimer = setTimeout(() => {
			this.reconnectTimer = null;
			if (!this.shouldReconnect) return;
			this.openConnection(false);
		}, RECONNECT_DELAY_MS);
	}

	private clearReconnectTimer(): void {
		if (this.reconnectTimer === null) return;
		clearTimeout(this.reconnectTimer);
		this.reconnectTimer = null;
	}
}

export const enginesStore = new EnginesStore();
