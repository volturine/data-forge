import type { EngineStatusResponse } from '$lib/types/compute';
import { listEngines, shutdownEngine as shutdownEngineApi } from '$lib/api/compute';
import { configStore } from './config.svelte';

export class EnginesStore {
	engines = $state<EngineStatusResponse[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);

	private interval: number | null = null;

	count = $derived(this.engines.length);

	async fetch(): Promise<void> {
		this.loading = true;
		this.error = null;

		await listEngines().match(
			(response) => {
				this.engines = response.engines;
			},
			(err) => {
				this.error = err.message;
			}
		);
		this.loading = false;
	}

	async shutdownEngine(analysisId: string): Promise<void> {
		await shutdownEngineApi(analysisId).match(
			() => {
				this.engines = this.engines.filter((e) => e.analysis_id !== analysisId);
			},
			(err) => {
				this.error = err.message;
				throw new Error(err.message);
			}
		);
	}

	async startPolling(): Promise<void> {
		if (this.interval !== null) return;

		// Try to load config but don't block polling if it fails
		if (!configStore.config) {
			await configStore.fetch();
		}

		this.fetch();

		this.interval = window.setInterval(() => {
			this.fetch();
		}, configStore.enginePoolingInterval);
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
