import { apiRequest, BASE_URL } from './client';

export interface ResultMetadata {
	analysis_id: string;
	row_count: number;
	column_count: number;
	columns_schema: Array<{ name: string; dtype: string }>;
	created_at: string;
}

export interface ResultData {
	columns: string[];
	data: Record<string, unknown>[];
	total_count: number;
	page: number;
	page_size: number;
}

export async function getResultMetadata(analysisId: string): Promise<ResultMetadata> {
	return apiRequest<ResultMetadata>(`/api/v1/results/${analysisId}`);
}

export async function getResultData(
	analysisId: string,
	page: number = 1,
	pageSize: number = 100
): Promise<ResultData> {
	return apiRequest<ResultData>(
		`/api/v1/results/${analysisId}/data?page=${page}&page_size=${pageSize}`
	);
}

export async function exportResult(
	analysisId: string,
	format: 'csv' | 'parquet' | 'excel' | 'json'
): Promise<Blob> {
	const response = await fetch(`${BASE_URL}/api/v1/results/${analysisId}/export`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ format })
	});

	if (!response.ok) {
		throw new Error(`Export failed: ${response.statusText}`);
	}

	return response.blob();
}

export async function deleteResult(analysisId: string): Promise<void> {
	await apiRequest<void>(`/api/v1/results/${analysisId}`, {
		method: 'DELETE'
	});
}
