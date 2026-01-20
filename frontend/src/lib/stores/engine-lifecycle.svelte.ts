import { untrack } from 'svelte';
import { spawnEngine, sendKeepalive, shutdownEngine, getEngineStatus } from '$lib/api/compute';
import type { EngineStatusResponse } from '$lib/types/compute';

const KEEPALIVE_INTERVAL = 30000; // 30 seconds
const SHUTDOWN_GRACE_MS = 30000; // kill idle engine after navigation away

class EngineLifecycle {
	status = $state<EngineStatusResponse | null>(null);
	error = $state<string | null>(null);
	// Non-reactive state to prevent infinite loops in effects
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
		// Use non-reactive checks to prevent effect re-triggers
		if (this._analysisId === analysisId && (this._starting || untrack(() => this.isActive))) return;

		this.cancelShutdownTimer();
		this.stop();
		this._analysisId = analysisId;
		this._starting = true;
		this.error = null;

		try {
			this.status = await spawnEngine(analysisId);
			this.startKeepalive();
		} catch (err) {
			this.error = err instanceof Error ? err.message : 'Failed to spawn engine';
			this.status = null;
		} finally {
			this._starting = false;
		}
	}

	async refresh(): Promise<void> {
		if (!this._analysisId) return;

		try {
			this.status = await getEngineStatus(this._analysisId);
		} catch {
			// Ignore refresh errors
		}
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

		try {
			await shutdownEngine(id);
		} catch {
			// Ignore shutdown errors
		}
	}

	private startKeepalive(): void {
		// Always clear any existing interval first
		this.stopKeepalive();
		this.cancelShutdownTimer();

		this._intervalId = setInterval(async () => {
			if (!this._analysisId) {
				this.stopKeepalive();
				return;
			}

			try {
				this.status = await sendKeepalive(this._analysisId);
			} catch {
				// Engine may have been terminated, try to respawn
				try {
					this.status = await spawnEngine(this._analysisId);
				} catch (err) {
					this.error = err instanceof Error ? err.message : 'Failed to respawn engine';
					this.stopKeepalive();
				}
			}
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
			try {
				await shutdownEngine(id);
			} catch {
				// Ignore shutdown errors
			} finally {
				if (this._analysisId === id) {
					this._analysisId = null;
					this.status = null;
				}
				this._shutdownTimer = null;
			}
		}, SHUTDOWN_GRACE_MS);
	}
}

export const engineLifecycle = new EngineLifecycle();
