import type {
	Analysis,
	AnalysisCreate,
	AnalysisGalleryItem,
	AnalysisUpdate
} from '$lib/types/analysis';
import { apiRequest, apiRequestWithHeaders } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export function createAnalysis(data: AnalysisCreate): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>('/v1/analysis', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function listAnalyses(): ResultAsync<AnalysisGalleryItem[], ApiError> {
	return apiRequest<AnalysisGalleryItem[]>('/v1/analysis');
}

export function getAnalysis(id: string): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>(`/v1/analysis/${id}`);
}

export function getAnalysisWithHeaders(
	id: string
): ResultAsync<{ analysis: Analysis; etag: string | null; version: string | null }, ApiError> {
	return apiRequestWithHeaders<Analysis>(`/v1/analysis/${id}`).map(({ data, headers }) => ({
		analysis: data,
		etag: headers.get('ETag'),
		version: headers.get('X-Analysis-Version')
	}));
}

export function updateAnalysis(id: string, data: AnalysisUpdate): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>(`/v1/analysis/${id}`, {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export function listAnalysisVersions(analysisId: string): ResultAsync<AnalysisVersion[], ApiError> {
	return apiRequest<AnalysisVersion[]>(`/v1/analysis/${analysisId}/versions`);
}

export function restoreAnalysisVersion(
	analysisId: string,
	version: number
): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>(`/v1/analysis/${analysisId}/versions/${version}/restore`, {
		method: 'POST'
	});
}

export function renameAnalysisVersion(
	analysisId: string,
	version: number,
	name: string
): ResultAsync<AnalysisVersion, ApiError> {
	return apiRequest<AnalysisVersion>(`/v1/analysis/${analysisId}/versions/${version}`, {
		method: 'PATCH',
		body: JSON.stringify({ name })
	});
}

export function deleteAnalysis(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/analysis/${id}`, {
		method: 'DELETE'
	});
}

export type AnalysisVersion = {
	id: string;
	analysis_id: string;
	version: number;
	name: string;
	description: string | null;
	pipeline_definition: Record<string, unknown>;
	created_at: string;
};

export type AnalysisExecuteResponse = {
	schema: Record<string, string>;
	rows: Array<Record<string, unknown>>;
	row_count?: number;
};

export function executeAnalysis(
	analysisId: string,
	pipeline: Record<string, unknown>,
	analysisTabId?: string | null
): ResultAsync<AnalysisExecuteResponse, ApiError> {
	const params = analysisTabId ? `?analysis_tab_id=${encodeURIComponent(analysisTabId)}` : '';
	return apiRequest<AnalysisExecuteResponse>(`/v1/analysis/${analysisId}/execute${params}`, {
		method: 'POST',
		body: JSON.stringify({ pipeline })
	});
}
