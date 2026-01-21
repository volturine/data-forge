import type { EngineStatusResponse } from '$lib/types/compute';
import { listEngines, shutdownEngine as shutdownEngineApi } from '$lib/api/compute';

const POLL_INTERVAL = 3000;

class EnginesStore {
	engines = $state<EngineStatusResponse[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);

	private interval: number | null = null;

	get count(): number {
		return this.engines.length;
	}

	get running(): EngineStatusResponse[] {
		return this.engines.filter((e) => e.status === 'running');
	}

	get idle(): EngineStatusResponse[] {
		return this.engines.filter((e) => e.status === 'idle');
	}

	async fetch(): Promise<void> {
		this.loading = true;
		this.error = null;

		listEngines().match(
			(response) => {
				this.engines = response.engines;
				this.loading = false;
			},
			(err) => {
				this.error = err.message;
				this.loading = false;
			}
		);
	}

	async shutdownEngine(analysisId: string): Promise<void> {
		shutdownEngineApi(analysisId).match(
			() => {
				this.engines = this.engines.filter((e) => e.analysis_id !== analysisId);
			},
			(err) => {
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	startPolling(): void {
		if (this.interval !== null) return;

		this.fetch();

		this.interval = window.setInterval(() => {
			this.fetch();
		}, POLL_INTERVAL);
	}

	stopPolling(): void {
		if (this.interval === null) return;

		clearInterval(this.interval);
		this.interval = null;
	}

	get isPolling(): boolean {
		return this.interval !== null;
	}
}

export const enginesStore = new EnginesStore();
