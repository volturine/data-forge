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

export interface AIProviderStatus {
	provider: string;
	configured: boolean;
	endpoint_url: string;
	default_model: string;
}

export function listAIProviders(): ResultAsync<AIProviderStatus[], ApiError> {
	return apiRequest<AIProviderStatus[]>('/v1/ai/providers', {
		method: 'POST'
	});
}

export function listAIModels(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null,
	organizationId?: string | null
): ResultAsync<AIModel[], ApiError> {
	const body: Record<string, string> = { provider };
	if (endpointUrl) body.endpoint_url = endpointUrl;
	if (apiKey) body.api_key = apiKey;
	if (organizationId) body.organization_id = organizationId;
	return apiRequest<AIModel[]>('/v1/ai/models', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function testAIConnection(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null,
	organizationId?: string | null
): ResultAsync<AIConnectionResult, ApiError> {
	const body: Record<string, string> = { provider };
	if (endpointUrl) body.endpoint_url = endpointUrl;
	if (apiKey) body.api_key = apiKey;
	if (organizationId) body.organization_id = organizationId;
	return apiRequest<AIConnectionResult>('/v1/ai/test', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}
