import { getConfig, type FrontendConfig } from '$lib/api/config';

export class ConfigStore {
	config = $state<FrontendConfig | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	private fetched = false;

	async fetch(): Promise<void> {
		if (this.fetched) return;

		this.loading = true;
		this.error = null;

		getConfig().match(
			(config) => {
				this.config = config;
				this.loading = false;
				this.fetched = true;
			},
			(err) => {
				this.error = err.message;
				this.loading = false;
			}
		);
	}

	// Getters with fallback defaults (in case config not loaded yet)
	get enginePoolingInterval(): number {
		return this.config?.engine_pooling_interval ?? 5000; // 5s default
	}

	get engineIdleTimeout(): number {
		return this.config?.engine_idle_timeout ?? 300; // 5min default
	}

	get jobTimeout(): number {
		return this.config?.job_timeout ?? 300; // 5min default
	}

	get timezone(): string {
		return this.config?.timezone ?? 'UTC';
	}

	get normalizeTz(): boolean {
		return this.config?.normalize_tz ?? false;
	}
}

export const configStore = new ConfigStore();
