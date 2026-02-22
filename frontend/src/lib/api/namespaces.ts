import { apiRequest } from './client';
import type { ApiError } from './client';
import { ResultAsync } from 'neverthrow';

export interface NamespaceListResponse {
	namespaces: string[];
}

export function listNamespaces(): ResultAsync<NamespaceListResponse, ApiError> {
	return apiRequest<NamespaceListResponse>('/v1/namespaces');
}
