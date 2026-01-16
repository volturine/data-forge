import type { DataSource, SchemaInfo } from '$lib/types/datasource';
import { BASE_URL, apiRequest } from './client';

export async function uploadFile(file: File, name: string): Promise<DataSource> {
	const formData = new FormData();
	formData.append('file', file);
	formData.append('name', name);

	const response = await fetch(`${BASE_URL}/api/v1/datasource/upload`, {
		method: 'POST',
		body: formData
	});

	if (!response.ok) {
		throw new Error(`Upload failed: ${response.statusText}`);
	}

	return response.json();
}

export async function connectDatabase(
	name: string,
	connectionString: string,
	query: string
): Promise<DataSource> {
	return apiRequest<DataSource>('/api/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'database',
			config: { connection_string: connectionString, query }
		})
	});
}

export async function connectApi(
	name: string,
	url: string,
	method: string = 'GET',
	headers?: Record<string, string>,
	auth?: Record<string, string>
): Promise<DataSource> {
	return apiRequest<DataSource>('/api/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'api',
			config: { url, method, headers, auth }
		})
	});
}

export async function listDatasources(): Promise<DataSource[]> {
	return apiRequest<DataSource[]>('/api/v1/datasource');
}

export async function getDatasource(id: string): Promise<DataSource> {
	return apiRequest<DataSource>(`/api/v1/datasource/${id}`);
}

export async function getDatasourceSchema(id: string): Promise<SchemaInfo> {
	return apiRequest<SchemaInfo>(`/api/v1/datasource/${id}/schema`);
}

export async function deleteDatasource(id: string): Promise<void> {
	await apiRequest<void>(`/api/v1/datasource/${id}`, {
		method: 'DELETE'
	});
}
