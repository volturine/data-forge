import type { ResultAsync } from 'neverthrow';
import { apiRequest } from './client';
import type { ApiError } from './client';

export interface AIModel {
	name: string;
	detail: string;
}

export interface AIConnectionResult {
	ok: boolean;
	detail: string;
}

export function listAIModels(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null
): ResultAsync<AIModel[], ApiError> {
	const params = new URLSearchParams({ provider });
	if (endpointUrl) params.set('endpoint_url', endpointUrl);
	if (apiKey) params.set('api_key', apiKey);
	return apiRequest<AIModel[]>(`/v1/ai/models?${params}`);
}

export function testAIConnection(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null
): ResultAsync<AIConnectionResult, ApiError> {
	const params = new URLSearchParams({ provider });
	if (endpointUrl) params.set('endpoint_url', endpointUrl);
	if (apiKey) params.set('api_key', apiKey);
	return apiRequest<AIConnectionResult>(`/v1/ai/test?${params}`);
}
