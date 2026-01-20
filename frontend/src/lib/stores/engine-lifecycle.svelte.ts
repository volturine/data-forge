import { untrack } from 'svelte';
import { spawnEngine, sendKeepalive, shutdownEngine, getEngineStatus } from '$lib/api/compute';
import type { EngineStatusResponse } from '$lib/types/compute';

const KEEPALIVE_INTERVAL = 30000;
const SHUTDOWN_GRACE_MS = 30000;

class EngineLifecycle {
	status = $state<EngineStatusResponse | null>(null);
	error = $state<string | null>(null);
	private _analysisId: string | null = null;
	private _starting = false;
	private _intervalId: ReturnType<typeof setInterval> | null = null;
	private _shutdownTimer: ReturnType<typeof setTimeout> | null = null;

	get analysisId(): string | null {
		return this._analysisId;
	}

	get isActive(): boolean {
		return this.status?.status === 'idle' || this.status?.status === 'running';
	}

	get isRunning(): boolean {
		return this.status?.status === 'running';
	}

	async start(analysisId: string): Promise<void> {
		if (this._analysisId === analysisId && (this._starting || untrack(() => this.isActive))) return;

		this.cancelShutdownTimer();
		this.stop();
		this._analysisId = analysisId;
		this._starting = true;
		this.error = null;

		spawnEngine(analysisId).match(
			(newStatus) => {
				this.status = newStatus;
				this.startKeepalive();
				this._starting = false;
			},
			(err) => {
				this.error = err.message;
				this.status = null;
				this._starting = false;
			}
		);
	}

	async refresh(): Promise<void> {
		if (!this._analysisId) return;

		getEngineStatus(this._analysisId).match(
			(newStatus) => {
				this.status = newStatus;
			},
			() => {
				// Ignore refresh errors
			}
		);
	}

	stop(): void {
		this.stopKeepalive();
		this._analysisId = null;
		this._starting = false;
		this.status = null;
		this.error = null;
	}

	async shutdown(): Promise<void> {
		if (!this._analysisId) return;

		const id = this._analysisId;
		this.stopKeepalive();
		this.cancelShutdownTimer();
		this._analysisId = null;
		this._starting = false;
		this.status = null;

		shutdownEngine(id).match(
			() => {},
			() => {}
		);
	}

	private startKeepalive(): void {
		this.stopKeepalive();
		this.cancelShutdownTimer();

		this._intervalId = setInterval(async () => {
			if (!this._analysisId) {
				this.stopKeepalive();
				return;
			}

			sendKeepalive(this._analysisId).match(
				(newStatus) => {
					this.status = newStatus;
				},
				() => {
					spawnEngine(this._analysisId!).match(
						(newStatus) => {
							this.status = newStatus;
						},
						(err) => {
							this.error = err.message;
							this.stopKeepalive();
						}
					);
				}
			);
		}, KEEPALIVE_INTERVAL);
	}

	private stopKeepalive(): void {
		if (this._intervalId !== null) {
			clearInterval(this._intervalId);
			this._intervalId = null;
		}
	}

	private cancelShutdownTimer(): void {
		if (this._shutdownTimer !== null) {
			clearTimeout(this._shutdownTimer);
			this._shutdownTimer = null;
		}
	}

	scheduleShutdown(): void {
		if (!this._analysisId) return;
		const id = this._analysisId;
		this.stopKeepalive();
		this.cancelShutdownTimer();

		this._shutdownTimer = setTimeout(async () => {
			shutdownEngine(id).match(
				() => {
					if (this._analysisId === id) {
						this._analysisId = null;
						this.status = null;
					}
				},
				() => {
					if (this._analysisId === id) {
						this._analysisId = null;
						this.status = null;
					}
				}
			);
			this._shutdownTimer = null;
		}, SHUTDOWN_GRACE_MS);
	}
}

export const engineLifecycle = new EngineLifecycle();
