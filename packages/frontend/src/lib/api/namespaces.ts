import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';

export interface NamespaceListResponse {
	namespaces: string[];
}

export interface NamespaceStoragePlan {
	name: string;
	bucket: string;
	uploads_root: string;
	clean_root: string;
	exports_root: string;
	runtime_artifacts_root: string;
	rules: string;
}

export interface NamespaceResponse {
	name: string;
	storage: NamespaceStoragePlan;
	created_bucket: boolean;
}

export function listNamespaces(): ResultAsync<NamespaceListResponse, ApiError> {
	return apiRequest<NamespaceListResponse>('/v1/namespaces');
}

export function previewNamespaceStorage(name: string): ResultAsync<NamespaceStoragePlan, ApiError> {
	const params = new URLSearchParams({ name });
	return apiRequest<NamespaceStoragePlan>(`/v1/namespaces/storage-plan?${params.toString()}`);
}

export function registerNamespace(name: string): ResultAsync<NamespaceResponse, ApiError> {
	return apiRequest<NamespaceResponse>('/v1/namespaces', {
		method: 'POST',
		body: JSON.stringify({ name })
	});
}
