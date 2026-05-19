import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';

export interface NamespaceListResponse {
	namespaces: string[];
}

export interface NamespaceResponse {
	name: string;
}

export function listNamespaces(): ResultAsync<NamespaceListResponse, ApiError> {
	return apiRequest<NamespaceListResponse>('/v1/namespaces');
}

export function registerNamespace(name: string): ResultAsync<NamespaceResponse, ApiError> {
	return apiRequest<NamespaceResponse>('/v1/namespaces', {
		method: 'POST',
		body: JSON.stringify({ name })
	});
}
