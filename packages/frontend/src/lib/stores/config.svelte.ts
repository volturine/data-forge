import { getConfig, type FrontendConfig } from '#lib/api/config.js';

export class ConfigStore {
	config = $state<FrontendConfig | null>(null);
	error = $state<string | null>(null);
	private fetched = false;
	private pending: Promise<void> | null = null;

	async fetch(): Promise<void> {
		if (this.fetched) return;
		if (this.pending) return this.pending;

		this.error = null;

		const request = (async () => {
			const result = await getConfig();
			if (result.isOk()) {
				this.config = result.value;
				this.fetched = true;
				this.error = null;
				return;
			}
			this.error = result.error.message;
		})();

		this.pending = request.finally(() => {
			this.pending = null;
		});

		return this.pending;
	}

	/**
	 * Invalidate the cache and refetch without clearing the current config.
	 * Clearing would unmount the app shell (ready depends on config !== null).
	 */
	async refresh(): Promise<void> {
		this.fetched = false;
		this.pending = null;
		return this.fetch();
	}

	get publicIdbDebug(): boolean {
		return this.config?.public_idb_debug ?? false;
	}

	get smtpEnabled(): boolean {
		return this.config?.smtp_enabled ?? false;
	}

	get telegramEnabled(): boolean {
		return this.config?.telegram_enabled ?? false;
	}

	get authRequired(): boolean {
		return this.config?.auth_required ?? true;
	}

	get verifyEmailAddress(): boolean {
		return this.config?.verify_email_address ?? true;
	}
}

export const configStore = new ConfigStore();
