import type { DataSource, SchemaInfo } from '$lib/types/datasource';
import { BASE_URL, apiRequest } from './client';
import { ResultAsync, err } from 'neverthrow';
import type { ApiError } from './client';

function createApiError(
	type: 'network' | 'http' | 'parse',
	message: string,
	status?: number,
	statusText?: string
): ApiError {
	return { type, message, status, statusText };
}

export function uploadFile(file: File, name: string): ResultAsync<DataSource, ApiError> {
	const formData = new FormData();
	formData.append('file', file);
	formData.append('name', name);

	return ResultAsync.fromPromise(
		fetch(`${BASE_URL}/v1/datasource/upload`, {
			method: 'POST',
			body: formData
		}),
		(error): ApiError =>
			createApiError('network', error instanceof Error ? error.message : 'Upload failed')
	).andThen((response) => {
		if (!response.ok) {
			return err(createApiError('http', response.statusText, response.status));
		}
		return ResultAsync.fromPromise(
			response.json() as Promise<DataSource>,
			(): ApiError => createApiError('parse', 'Failed to parse upload response')
		);
	});
}

export function connectDatabase(
	name: string,
	connectionString: string,
	query: string
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'database',
			config: { connection_string: connectionString, query }
		})
	});
}

export function connectApi(
	name: string,
	url: string,
	method: string = 'GET',
	headers?: Record<string, string>,
	auth?: Record<string, string>
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'api',
			config: { url, method, headers, auth }
		})
	});
}

export function listDatasources(): ResultAsync<DataSource[], ApiError> {
	return apiRequest<DataSource[]>('/v1/datasource');
}

export function getDatasource(id: string): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>(`/v1/datasource/${id}`);
}

export function getDatasourceSchema(id: string): ResultAsync<SchemaInfo, ApiError> {
	return apiRequest<SchemaInfo>(`/v1/datasource/${id}/schema`);
}

export function deleteDatasource(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/datasource/${id}`, {
		method: 'DELETE'
	});
}
