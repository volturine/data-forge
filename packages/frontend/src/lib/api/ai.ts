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

function providerRequestBody(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null,
	organizationId?: string | null
): string {
	const body: Record<string, string> = { provider };
	if (endpointUrl) body.endpoint_url = endpointUrl;
	if (apiKey) body.api_key = apiKey;
	if (organizationId) body.organization_id = organizationId;
	return JSON.stringify(body);
}

export function listAIModels(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null,
	organizationId?: string | null
): ResultAsync<AIModel[], ApiError> {
	return apiRequest<AIModel[]>('/v1/ai/models', {
		method: 'POST',
		body: providerRequestBody(provider, endpointUrl, apiKey, organizationId)
	});
}

export function testAIConnection(
	provider: string,
	endpointUrl?: string | null,
	apiKey?: string | null,
	organizationId?: string | null
): ResultAsync<AIConnectionResult, ApiError> {
	return apiRequest<AIConnectionResult>('/v1/ai/test', {
		method: 'POST',
		body: providerRequestBody(provider, endpointUrl, apiKey, organizationId)
	});
}
