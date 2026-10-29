import type { ResultAsync } from 'neverthrow';

import { apiRequest } from './client';
import type { ApiError } from './client';
import type { Udf, UdfClone, UdfCreate, UdfExport, UdfImport, UdfUpdate } from '#lib/types/udf.js';
import { withQuery } from './query';

export function listUdfs(
	params?: {
		q?: string;
		dtype_key?: string;
		tag?: string;
	},
	options?: RequestInit
): ResultAsync<Udf[], ApiError> {
	return apiRequest<Udf[]>(
		withQuery('/v1/udf', {
			q: params?.q,
			dtype_key: params?.dtype_key,
			tag: params?.tag
		}),
		options
	);
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

export function exportUdfs(): ResultAsync<UdfExport, ApiError> {
	return apiRequest<UdfExport>('/v1/udf/export');
}

export function importUdfs(payload: UdfImport): ResultAsync<Udf[], ApiError> {
	return apiRequest<Udf[]>('/v1/udf/import', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}
