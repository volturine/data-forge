import { apiRequest } from './client';
import type { ApiError } from './client';
import { ResultAsync } from 'neverthrow';
import type { DataSource } from '$lib/types/datasource';

export interface ExcelPreflightResponse {
	preflight_id: string;
	sheet_name: string | null;
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
	sheet_name: string | null;
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
		end_row?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
		cell_range?: string;
	}
): ResultAsync<ExcelPreflightResponse, ApiError> {
	const formData = new FormData();
	formData.append('file', file);
	if (params.sheet_name) formData.append('sheet_name', params.sheet_name);
	if (params.start_row !== undefined) formData.append('start_row', String(params.start_row));
	if (params.start_col !== undefined) formData.append('start_col', String(params.start_col));
	if (params.end_col !== undefined) formData.append('end_col', String(params.end_col));
	if (params.end_row !== undefined) formData.append('end_row', String(params.end_row));
	if (params.has_header !== undefined) formData.append('has_header', String(params.has_header));
	if (params.table_name) formData.append('table_name', params.table_name);
	if (params.named_range) formData.append('named_range', params.named_range);
	if (params.cell_range) formData.append('cell_range', params.cell_range);
	return apiRequest<ExcelPreflightResponse>('/v1/datasource/preflight', {
		method: 'POST',
		body: formData
	});
}

export function preflightExcelFromPath(
	filePath: string,
	params: {
		sheet_name?: string;
		start_row?: number;
		start_col?: number;
		end_col?: number;
		end_row?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
		cell_range?: string;
	}
): ResultAsync<ExcelPreflightResponse, ApiError> {
	return apiRequest<ExcelPreflightResponse>('/v1/datasource/preflight-path', {
		method: 'POST',
		body: JSON.stringify({ file_path: filePath, ...params })
	});
}

export function previewExcel(
	preflightId: string,
	params: {
		sheet_name: string;
		start_row?: number;
		start_col?: number;
		end_col?: number;
		end_row?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
		cell_range?: string;
	}
): ResultAsync<ExcelPreviewResponse, ApiError> {
	const query = new URLSearchParams();
	query.set('sheet_name', params.sheet_name);
	if (params.start_row !== undefined) query.set('start_row', String(params.start_row));
	if (params.start_col !== undefined) query.set('start_col', String(params.start_col));
	if (params.end_col !== undefined) query.set('end_col', String(params.end_col));
	if (params.end_row !== undefined) query.set('end_row', String(params.end_row));
	if (params.has_header !== undefined) query.set('has_header', String(params.has_header));
	if (params.table_name) query.set('table_name', params.table_name);
	if (params.named_range) query.set('named_range', params.named_range);
	if (params.cell_range) query.set('cell_range', params.cell_range);
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
		end_row?: number;
		has_header?: boolean;
		table_name?: string;
		named_range?: string;
		cell_range?: string;
	}
): ResultAsync<DataSource, ApiError> {
	const formData = new FormData();
	formData.append('preflight_id', preflightId);
	formData.append('name', name);
	if (params.sheet_name) formData.append('sheet_name', params.sheet_name);
	if (params.start_row !== undefined) formData.append('start_row', String(params.start_row));
	if (params.start_col !== undefined) formData.append('start_col', String(params.start_col));
	if (params.end_col !== undefined) formData.append('end_col', String(params.end_col));
	if (params.end_row !== undefined) formData.append('end_row', String(params.end_row));
	if (params.has_header !== undefined) formData.append('has_header', String(params.has_header));
	if (params.table_name) formData.append('table_name', params.table_name);
	if (params.named_range) formData.append('named_range', params.named_range);
	if (params.cell_range) formData.append('cell_range', params.cell_range);
	return apiRequest<DataSource>('/v1/datasource/confirm', {
		method: 'POST',
		body: formData
	});
}
