import type { EngineStatusResponse } from '$lib/types/compute';
import {
	connectEnginesStream,
	shutdownAnalysisEngine as shutdownAnalysisEngineApi,
	shutdownEngineByIdentity
} from '$lib/api/compute';
import { ReconnectionManager } from './reconnection-manager';
import { SvelteSet } from 'svelte/reactivity';

const RECONNECT_DELAY_MS = 1_000;

export type EnginesConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

function engineIdentityKey(engine: EngineStatusResponse): string {
	return `${engine.scope ?? 'analysis_interactive'}:${engine.resource_id}`;
}

export class EnginesStore {
	engines = $state.raw<EngineStatusResponse[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	status = $state<EnginesConnectionStatus>('disconnected');
	private shuttingDown = new SvelteSet<string>();

	private connection: { close: () => void } | null = null;
	private reconnect = new ReconnectionManager(RECONNECT_DELAY_MS);
	private shouldReconnect = false;
	private subscribers = 0;
	private holdUntilEmpty = false;

	count = $derived(this.engines.length);

	startStream(): void {
		this.subscribers++;
		this.holdUntilEmpty = false;
		if (this.shouldReconnect) return;
		this.shouldReconnect = true;
		this.openConnection(true);
	}

	stopStream(): void {
		this.subscribers = Math.max(0, this.subscribers - 1);
		if (this.subscribers > 0) return;
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

	async shutdownEngine(engine: EngineStatusResponse): Promise<void> {
		const key = engineIdentityKey(engine);
		this.shuttingDown.add(key);
		this.engines = this.engines.filter((item) => engineIdentityKey(item) !== key);
		await shutdownEngineByIdentity(
			engine.scope ?? 'analysis_interactive',
			engine.resource_id
		).match(
			() => {},
			(err) => {
				this.shuttingDown.delete(key);
				if (err.status === 404 || err.status === 409) {
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
			() => {},
			(err) => {
				if (err.status === 404 || err.status === 409) {
					this.error = null;
					return;
				}
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	reset(): void {
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
			onSnapshot: (engines) => {
				for (const key of this.shuttingDown) {
					if (engines.some((engine) => engineIdentityKey(engine) === key)) continue;
					this.shuttingDown.delete(key);
				}
				this.engines = engines.filter(
					(engine) => !this.shuttingDown.has(engineIdentityKey(engine))
				);
				this.loading = false;
				this.error = null;
				this.status = 'connected';
				if (this.holdUntilEmpty && this.subscribers === 0 && this.engines.length === 0) {
					this.holdUntilEmpty = false;
					this.shouldReconnect = false;
					this.clearReconnectTimer();
					this.connection?.close();
				}
			},
			onError: (message) => {
				if (/not authenticated/i.test(message)) {
					this.holdUntilEmpty = false;
					this.shouldReconnect = false;
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
