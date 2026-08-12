import { getConfig, type FrontendConfig } from '$lib/api/config';

export class ConfigStore {
	config = $state<FrontendConfig | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	private fetched = false;
	private pending: Promise<void> | null = null;

	async fetch(): Promise<void> {
		if (this.fetched) return;
		if (this.pending) return this.pending;

		this.loading = true;
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
			this.loading = false;
			this.pending = null;
		});

		return this.pending;
	}

	/** True once fetch settled (success or failure). Used to leave the bootstrap spinner. */
	get settled(): boolean {
		return this.fetched || this.error !== null;
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

	get timezone(): string {
		return this.config?.timezone ?? 'UTC';
	}

	get normalizeTz(): boolean {
		return this.config?.normalize_tz ?? false;
	}

	get auditLogBatchSize(): number {
		return this.config?.log_client_batch_size ?? 20;
	}

	get auditLogFlushIntervalMs(): number {
		return this.config?.log_client_flush_interval_ms ?? 5000;
	}

	get auditLogDedupeWindowMs(): number {
		return this.config?.log_client_dedupe_window_ms ?? 500;
	}

	get auditLogFlushCooldownMs(): number {
		return this.config?.log_client_flush_cooldown_ms ?? 3000;
	}

	get logQueueMaxSize(): number {
		return this.config?.log_queue_max_size ?? 2000;
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
