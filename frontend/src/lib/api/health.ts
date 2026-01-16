import type { HealthResponse } from '$lib/types/api-responses';
import { apiRequest } from './client';

export async function checkHealth(): Promise<HealthResponse> {
	return apiRequest<HealthResponse>('/api/v1/health/');
}
