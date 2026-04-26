import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';
import type { DataSource } from '$lib/types/datasource';

export interface ExcelParams {
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

interface Settable {
	set(key: string, value: string): void;
}

function appendExcelParams(target: Settable, params: ExcelParams): void {
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined) continue;
		target.set(key, String(value));
	}
}

export function preflightExcel(
	file: File,
	params: ExcelParams
): ResultAsync<ExcelPreflightResponse, ApiError> {
	const body = new FormData();
	body.append('file', file);
	appendExcelParams(body, params);
	return apiRequest<ExcelPreflightResponse>('/v1/datasource/preflight', {
		method: 'POST',
		body
	});
}

export function preflightExcelFromPath(
	filePath: string,
	params: ExcelParams
): ResultAsync<ExcelPreflightResponse, ApiError> {
	return apiRequest<ExcelPreflightResponse>('/v1/datasource/preflight-path', {
		method: 'POST',
		body: JSON.stringify({ file_path: filePath, ...params })
	});
}

export function previewExcel(
	preflightId: string,
	params: ExcelParams & { sheet_name: string }
): ResultAsync<ExcelPreviewResponse, ApiError> {
	const query = new URLSearchParams();
	appendExcelParams(query, params);
	return apiRequest<ExcelPreviewResponse>(
		`/v1/datasource/preflight/${preflightId}/preview?${query}`
	);
}

export function confirmExcel(
	preflightId: string,
	name: string,
	description: string,
	params: ExcelParams
): ResultAsync<DataSource, ApiError> {
	const body = new FormData();
	body.append('preflight_id', preflightId);
	body.append('name', name);
	body.append('description', description);
	appendExcelParams(body, params);
	return apiRequest<DataSource>('/v1/datasource/confirm', {
		method: 'POST',
		body
	});
}
