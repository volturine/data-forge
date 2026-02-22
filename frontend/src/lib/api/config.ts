import { apiRequest } from './client';
import type { ApiError } from './client';
import { ResultAsync } from 'neverthrow';

export interface FrontendConfig {
	engine_pooling_interval: number; // milliseconds
	engine_idle_timeout: number; // seconds
	job_timeout: number; // seconds
	timezone: string;
	normalize_tz: boolean;
	log_client_batch_size: number;
	log_client_flush_interval_ms: number;
	log_client_dedupe_window_ms: number;
	log_client_flush_cooldown_ms: number;
	log_queue_max_size: number;
	public_idb_debug: boolean;
	smtp_enabled: boolean;
	telegram_enabled: boolean;
	default_namespace: string;
}

export function getConfig(): ResultAsync<FrontendConfig, ApiError> {
	return apiRequest<FrontendConfig>('/v1/config');
}
