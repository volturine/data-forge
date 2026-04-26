import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { FrontendConfig } from '$lib/api/config';

const mockGetConfig = vi.fn();

vi.mock('$lib/api/config', () => ({
	getConfig: (...args: unknown[]) => mockGetConfig(...args)
}));

const { ConfigStore } = await import('./config.svelte');

function makeConfig(overrides: Partial<FrontendConfig> = {}): FrontendConfig {
	return {
		engine_idle_timeout: 600,
		job_timeout: 120,
		timezone: 'Europe/Berlin',
		normalize_tz: true,
		log_client_batch_size: 50,
		log_client_flush_interval_ms: 2000,
		log_client_dedupe_window_ms: 300,
		log_client_flush_cooldown_ms: 1500,
		log_queue_max_size: 5000,
		public_idb_debug: true,
		smtp_enabled: true,
		telegram_enabled: false,
		default_namespace: 'test-ns',
		auth_required: true,
		verify_email_address: true,
		...overrides
	};
}

function mockSuccess(config: FrontendConfig) {
	mockGetConfig.mockReturnValue({
		match: (onOk: (c: FrontendConfig) => void, _onErr: (e: { message: string }) => void) => {
			onOk(config);
			return Promise.resolve();
		}
	});
}

function mockError(message: string) {
	mockGetConfig.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

describe('ConfigStore', () => {
	let store: InstanceType<typeof ConfigStore>;

	beforeEach(() => {
		vi.clearAllMocks();
		store = new ConfigStore();
	});

	describe('initial state', () => {
		test('config is null', () => {
			expect(store.config).toBeNull();
		});

		test('loading is false', () => {
			expect(store.loading).toBe(false);
		});

		test('error is null', () => {
			expect(store.error).toBeNull();
		});
	});

	describe('getter defaults before fetch', () => {
		test('engineIdleTimeout returns 300', () => {
			expect(store.engineIdleTimeout).toBe(300);
		});

		test('jobTimeout returns 300', () => {
			expect(store.jobTimeout).toBe(300);
		});

		test('timezone returns UTC', () => {
			expect(store.timezone).toBe('UTC');
		});

		test('normalizeTz returns false', () => {
			expect(store.normalizeTz).toBe(false);
		});

		test('auditLogBatchSize returns 20', () => {
			expect(store.auditLogBatchSize).toBe(20);
		});

		test('auditLogFlushIntervalMs returns 5000', () => {
			expect(store.auditLogFlushIntervalMs).toBe(5000);
		});

		test('auditLogDedupeWindowMs returns 500', () => {
			expect(store.auditLogDedupeWindowMs).toBe(500);
		});

		test('auditLogFlushCooldownMs returns 3000', () => {
			expect(store.auditLogFlushCooldownMs).toBe(3000);
		});

		test('logQueueMaxSize returns 2000', () => {
			expect(store.logQueueMaxSize).toBe(2000);
		});

		test('publicIdbDebug returns false', () => {
			expect(store.publicIdbDebug).toBe(false);
		});

		test('smtpEnabled returns false', () => {
			expect(store.smtpEnabled).toBe(false);
		});

		test('telegramEnabled returns false', () => {
			expect(store.telegramEnabled).toBe(false);
		});

		test('authRequired returns true', () => {
			expect(store.authRequired).toBe(true);
		});

		test('verifyEmailAddress returns true', () => {
			expect(store.verifyEmailAddress).toBe(true);
		});
	});

	describe('fetch success', () => {
		test('populates config and clears loading', async () => {
			const cfg = makeConfig();
			mockSuccess(cfg);

			await store.fetch();

			expect(store.config).toEqual(cfg);
			expect(store.loading).toBe(false);
			expect(store.error).toBeNull();
		});

		test('getters return fetched values', async () => {
			mockSuccess(
				makeConfig({
					timezone: 'America/New_York',
					smtp_enabled: true,
					auth_required: false,
					verify_email_address: false
				})
			);

			await store.fetch();

			expect(store.timezone).toBe('America/New_York');
			expect(store.smtpEnabled).toBe(true);
			expect(store.authRequired).toBe(false);
			expect(store.verifyEmailAddress).toBe(false);
		});
	});

	describe('fetch error', () => {
		test('sets error message and clears loading', async () => {
			mockError('Network failure');

			await store.fetch();

			expect(store.error).toBe('Network failure');
			expect(store.loading).toBe(false);
			expect(store.config).toBeNull();
		});

		test('getters still return defaults after error', async () => {
			mockError('boom');
			await store.fetch();
			expect(store.timezone).toBe('UTC');
		});
	});

	describe('fetch deduplication', () => {
		test('second fetch after success is a no-op', async () => {
			mockSuccess(makeConfig());
			await store.fetch();
			expect(mockGetConfig).toHaveBeenCalledTimes(1);

			await store.fetch();
			expect(mockGetConfig).toHaveBeenCalledTimes(1);
		});

		test('concurrent fetches share the same promise', async () => {
			let resolve!: () => void;
			const delayed = new Promise<void>((r) => {
				resolve = r;
			});

			mockGetConfig.mockReturnValue({
				match: (onOk: (c: FrontendConfig) => void) => {
					onOk(makeConfig());
					return delayed;
				}
			});

			const p1 = store.fetch();
			const p2 = store.fetch();

			resolve();
			await p1;
			await p2;

			expect(mockGetConfig).toHaveBeenCalledTimes(1);
		});
	});

	describe('fetched guard', () => {
		test('error path does not set fetched flag — allows retry', async () => {
			mockError('first try');
			await store.fetch();
			expect(store.error).toBe('first try');
			expect(mockGetConfig).toHaveBeenCalledTimes(1);

			mockSuccess(makeConfig());
			await store.fetch();
			expect(store.config).not.toBeNull();
			expect(mockGetConfig).toHaveBeenCalledTimes(2);
		});
	});
});
