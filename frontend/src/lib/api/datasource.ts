import type { CSVOptions, DataSource, SchemaInfo } from '$lib/types/datasource';
import { apiRequest } from './client';
import { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

function createApiError(
	type: 'network' | 'http' | 'parse',
	message: string,
	status?: number,
	statusText?: string
): ApiError {
	return { type, message, status, statusText };
}

export function uploadFile(
	file: File,
	name: string,
	csvOptions?: CSVOptions
): ResultAsync<DataSource, ApiError> {
	const formData = new FormData();
	formData.append('file', file);
	formData.append('name', name);

	if (csvOptions) {
		formData.append('delimiter', csvOptions.delimiter);
		formData.append('quote_char', csvOptions.quote_char);
		formData.append('has_header', String(csvOptions.has_header));
		formData.append('skip_rows', String(csvOptions.skip_rows));
		formData.append('encoding', csvOptions.encoding);
	}

	return apiRequest<DataSource>('/v1/datasource/upload', {
		method: 'POST',
		body: formData
	}).mapErr((error) => {
		if (error.type === 'network') {
			return createApiError('network', error.message || 'Upload failed');
		}
		return error;
	});
}

export interface ExcelPreflightResponse {
	preflight_id: string;
	sheet_names: string[];
	tables: Record<string, string[]>;
	named_ranges: string[];
	preview: Array<Array<string | null>>;
	start_row: number;
	start_col: number;
	end_col: number;
	detected_end_row: number | null;
}

export interface ExcelPreviewResponse {
	preview: Array<Array<string | null>>;
	start_row: number;
	start_col: number;
	end_col: number;
	detected_end_row: number | null;
}

export function preflightExcel(
	file: File,
	params: {
		sheet_name?: string;
		start_row?: number;
		start_col?: number;
		end_col?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
	}
): ResultAsync<ExcelPreflightResponse, ApiError> {
	const formData = new FormData();
	formData.append('file', file);
	if (params.sheet_name) formData.append('sheet_name', params.sheet_name);
	if (params.start_row !== undefined) formData.append('start_row', String(params.start_row));
	if (params.start_col !== undefined) formData.append('start_col', String(params.start_col));
	if (params.end_col !== undefined) formData.append('end_col', String(params.end_col));
	if (params.has_header !== undefined) formData.append('has_header', String(params.has_header));
	if (params.table_name) formData.append('table_name', params.table_name);
	if (params.named_range) formData.append('named_range', params.named_range);
	return apiRequest<ExcelPreflightResponse>('/v1/datasource/preflight', {
		method: 'POST',
		body: formData
	});
}

export function previewExcel(
	preflightId: string,
	params: {
		sheet_name: string;
		start_row?: number;
		start_col?: number;
		end_col?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
	}
): ResultAsync<ExcelPreviewResponse, ApiError> {
	const query = new URLSearchParams();
	query.set('sheet_name', params.sheet_name);
	if (params.start_row !== undefined) query.set('start_row', String(params.start_row));
	if (params.start_col !== undefined) query.set('start_col', String(params.start_col));
	if (params.end_col !== undefined) query.set('end_col', String(params.end_col));
	if (params.has_header !== undefined) query.set('has_header', String(params.has_header));
	if (params.table_name) query.set('table_name', params.table_name);
	if (params.named_range) query.set('named_range', params.named_range);
	return apiRequest<ExcelPreviewResponse>(
		`/v1/datasource/preflight/${preflightId}/preview?${query}`
	);
}

export function confirmExcel(
	preflightId: string,
	name: string,
	params: {
		sheet_name?: string;
		start_row?: number;
		start_col?: number;
		end_col?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
	}
): ResultAsync<DataSource, ApiError> {
	const formData = new FormData();
	formData.append('preflight_id', preflightId);
	formData.append('name', name);
	if (params.sheet_name) formData.append('sheet_name', params.sheet_name);
	if (params.start_row !== undefined) formData.append('start_row', String(params.start_row));
	if (params.start_col !== undefined) formData.append('start_col', String(params.start_col));
	if (params.end_col !== undefined) formData.append('end_col', String(params.end_col));
	if (params.has_header !== undefined) formData.append('has_header', String(params.has_header));
	if (params.table_name) formData.append('table_name', params.table_name);
	if (params.named_range) formData.append('named_range', params.named_range);
	return apiRequest<DataSource>('/v1/datasource/confirm', {
		method: 'POST',
		body: formData
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

export function connectDuckDB(
	name: string,
	query: string,
	dbPath?: string,
	readOnly: boolean = true
): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>('/v1/datasource/connect', {
		method: 'POST',
		body: JSON.stringify({
			name,
			source_type: 'duckdb',
			config: { db_path: dbPath, query, read_only: readOnly }
		})
	});
}

export function listDatasources(): ResultAsync<DataSource[], ApiError> {
	return apiRequest<DataSource[]>('/v1/datasource');
}

export function getDatasource(id: string): ResultAsync<DataSource, ApiError> {
	return apiRequest<DataSource>(`/v1/datasource/${id}`);
}

export function getDatasourceSchema(
	id: string,
	sheetName?: string
): ResultAsync<SchemaInfo, ApiError> {
	const params = sheetName ? `?sheet_name=${encodeURIComponent(sheetName)}` : '';
	return apiRequest<SchemaInfo>(`/v1/datasource/${id}/schema${params}`);
}

export function deleteDatasource(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/datasource/${id}`, {
		method: 'DELETE'
	});
}
