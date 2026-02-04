import { apiRequest } from './client';
import type { ApiError } from './client';
import { ResultAsync } from 'neverthrow';

export interface FrontendConfig {
	engine_pooling_interval: number; // milliseconds
	engine_idle_timeout: number; // seconds
	job_timeout: number; // seconds
	timezone: string;
	normalize_tz: boolean;
}

export function getConfig(): ResultAsync<FrontendConfig, ApiError> {
	return apiRequest<FrontendConfig>('/v1/config');
}
