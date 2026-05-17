import type { ResultAsync } from 'neverthrow';

import { apiRequest } from './client';
import type { ApiError } from './client';
import type { Udf, UdfClone, UdfCreate, UdfExport, UdfImport, UdfUpdate } from '$lib/types/udf';

export function listUdfs(params?: {
	q?: string;
	dtype_key?: string;
	tag?: string;
}): ResultAsync<Udf[], ApiError> {
	const search = new URLSearchParams();
	if (params?.q) search.set('q', params.q);
	if (params?.dtype_key) search.set('dtype_key', params.dtype_key);
	if (params?.tag) search.set('tag', params.tag);
	const query = search.toString();
	const endpoint = query ? `/v1/udf?${query}` : '/v1/udf';
	return apiRequest<Udf[]>(endpoint);
}

export function getUdf(id: string): ResultAsync<Udf, ApiError> {
	return apiRequest<Udf>(`/v1/udf/${id}`);
}

export function createUdf(data: UdfCreate): ResultAsync<Udf, ApiError> {
	return apiRequest<Udf>('/v1/udf', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function updateUdf(id: string, data: UdfUpdate): ResultAsync<Udf, ApiError> {
	return apiRequest<Udf>(`/v1/udf/${id}`, {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export function deleteUdf(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/udf/${id}`, {
		method: 'DELETE'
	});
}

export function cloneUdf(id: string, data: UdfClone): ResultAsync<Udf, ApiError> {
	return apiRequest<Udf>(`/v1/udf/${id}/clone`, {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function matchUdfs(dtypes: string[]): ResultAsync<Udf[], ApiError> {
	const params = new URLSearchParams();
	for (const dtype of dtypes) {
		params.append('dtypes', dtype);
	}
	return apiRequest<Udf[]>(`/v1/udf/match?${params.toString()}`);
}

export function exportUdfs(): ResultAsync<UdfExport, ApiError> {
	return apiRequest<UdfExport>('/v1/udf/export');
}

export function importUdfs(payload: UdfImport): ResultAsync<Udf[], ApiError> {
	return apiRequest<Udf[]>('/v1/udf/import', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}
