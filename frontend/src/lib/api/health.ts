import type { ResultAsync } from 'neverthrow';
import type { HealthResponse } from '$lib/types/api-responses';
import { apiRequest } from './client';
import type { ApiError } from './client';

export function checkHealth(): ResultAsync<HealthResponse, ApiError> {
	return apiRequest<HealthResponse>('/v1/health');
}
