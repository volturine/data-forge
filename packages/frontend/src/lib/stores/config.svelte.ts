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

		const request = getConfig().match(
			(config) => {
				this.config = config;
				this.fetched = true;
			},
			(err) => {
				this.error = err.message;
			}
		);

		this.pending = request.finally(() => {
			this.loading = false;
			this.pending = null;
		});

		return this.pending;
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
