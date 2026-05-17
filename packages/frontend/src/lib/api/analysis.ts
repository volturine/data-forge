import type {
	Analysis,
	AnalysisCreate,
	AnalysisGalleryItem,
	AnalysisTemplateDetail,
	AnalysisTemplateSummary,
	AnalysisUpdate,
	DuplicateAnalysisRequest,
	GenerateAnalysisRequest,
	GeneratedAnalysisResponse,
	ImportAnalysisRequest
} from '$lib/types/analysis';
import { apiRequest, apiRequestWithHeaders } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export const createAnalysis = (data: AnalysisCreate): ResultAsync<Analysis, ApiError> =>
	apiRequest<Analysis>('/v1/analysis', { method: 'POST', body: JSON.stringify(data) });

export const listAnalyses = (): ResultAsync<AnalysisGalleryItem[], ApiError> =>
	apiRequest<AnalysisGalleryItem[]>('/v1/analysis');

export const listFavoriteAnalyses = (): ResultAsync<AnalysisGalleryItem[], ApiError> =>
	apiRequest<AnalysisGalleryItem[]>('/v1/analysis/favorites');

export const listAnalysisTemplates = (): ResultAsync<AnalysisTemplateSummary[], ApiError> =>
	apiRequest<AnalysisTemplateSummary[]>('/v1/analysis/templates');

export const getAnalysisTemplate = (
	templateId: string
): ResultAsync<AnalysisTemplateDetail, ApiError> =>
	apiRequest<AnalysisTemplateDetail>(`/v1/analysis/templates/${templateId}`);

export const generateAnalysis = (
	data: GenerateAnalysisRequest
): ResultAsync<GeneratedAnalysisResponse, ApiError> =>
	apiRequest<GeneratedAnalysisResponse>('/v1/analysis/generate', {
		method: 'POST',
		body: JSON.stringify(data)
	});

export const duplicateAnalysis = (
	id: string,
	data: DuplicateAnalysisRequest
): ResultAsync<Analysis, ApiError> =>
	apiRequest<Analysis>(`/v1/analysis/${id}/duplicate`, {
		method: 'POST',
		body: JSON.stringify(data)
	});

export const importAnalysis = (data: ImportAnalysisRequest): ResultAsync<Analysis, ApiError> =>
	apiRequest<Analysis>('/v1/analysis/import', {
		method: 'POST',
		body: JSON.stringify(data)
	});

export const getAnalysis = (id: string): ResultAsync<Analysis, ApiError> =>
	apiRequest<Analysis>(`/v1/analysis/${id}`);

export function getAnalysisWithHeaders(
	id: string
): ResultAsync<{ analysis: Analysis; etag: string | null; version: string | null }, ApiError> {
	return apiRequestWithHeaders<Analysis>(`/v1/analysis/${id}`).map(({ data, headers }) => ({
		analysis: data,
		etag: headers.get('ETag'),
		version: headers.get('X-Analysis-Version')
	}));
}

export function updateAnalysis(
	id: string,
	data: AnalysisUpdate,
	version?: string | null
): ResultAsync<{ analysis: Analysis; version: string | null }, ApiError> {
	const headers: Record<string, string> = {};
	if (version) headers['If-Match'] = version;
	return apiRequestWithHeaders<Analysis>(`/v1/analysis/${id}`, {
		method: 'PUT',
		body: JSON.stringify(data),
		headers
	}).map(({ data: analysis, headers: h }) => ({
		analysis,
		version: h.get('X-Analysis-Version')
	}));
}

export const listAnalysisVersions = (
	analysisId: string
): ResultAsync<AnalysisVersion[], ApiError> =>
	apiRequest<AnalysisVersion[]>(`/v1/analysis/${analysisId}/versions`);

export const restoreAnalysisVersion = (
	analysisId: string,
	version: number
): ResultAsync<Analysis, ApiError> =>
	apiRequest<Analysis>(`/v1/analysis/${analysisId}/versions/${version}/restore`, {
		method: 'POST'
	});

export const renameAnalysisVersion = (
	analysisId: string,
	version: number,
	name: string
): ResultAsync<AnalysisVersion, ApiError> =>
	apiRequest<AnalysisVersion>(`/v1/analysis/${analysisId}/versions/${version}`, {
		method: 'PATCH',
		body: JSON.stringify({ name })
	});

export const deleteAnalysisVersion = (
	analysisId: string,
	version: number
): ResultAsync<void, ApiError> =>
	apiRequest<void>(`/v1/analysis/${analysisId}/versions/${version}`, { method: 'DELETE' });

export const deleteAnalysis = (id: string): ResultAsync<void, ApiError> =>
	apiRequest<void>(`/v1/analysis/${id}`, { method: 'DELETE' });

export type AnalysisFavoriteStatus = {
	analysis_id: string;
	is_favorite: boolean;
};

export const favoriteAnalysis = (id: string): ResultAsync<AnalysisFavoriteStatus, ApiError> =>
	apiRequest<AnalysisFavoriteStatus>(`/v1/analysis/${id}/favorite`, { method: 'POST' });

export const unfavoriteAnalysis = (id: string): ResultAsync<AnalysisFavoriteStatus, ApiError> =>
	apiRequest<AnalysisFavoriteStatus>(`/v1/analysis/${id}/favorite`, { method: 'DELETE' });

export type AnalysisVersion = {
	id: string;
	analysis_id: string;
	version: number;
	name: string;
	description: string | null;
	pipeline_definition?: Record<string, unknown>;
	created_at: string;
};

export type AnalysisPreviewResponse = {
	schema: Record<string, string>;
	rows: Array<Record<string, unknown>>;
	row_count?: number;
};

export type CodeExportFormat = 'polars' | 'sql';

export type CodeExportRequest = {
	format: CodeExportFormat;
	tab_id?: string | null;
};

export type CodeExportResponse = {
	code: string;
	warnings: string[];
	filename: string;
	format: CodeExportFormat;
	tab_id?: string | null;
};

export const previewAnalysis = (
	analysisId: string,
	pipeline: Record<string, unknown>
): ResultAsync<AnalysisPreviewResponse, ApiError> =>
	apiRequest<AnalysisPreviewResponse>(`/v1/analysis/${analysisId}/preview`, {
		method: 'POST',
		body: JSON.stringify({ pipeline })
	});

export const validateAnalysis = (
	data: AnalysisCreate
): ResultAsync<{ valid: boolean; payload: { tabs: AnalysisCreate['tabs'] } }, ApiError> =>
	apiRequest<{ valid: boolean; payload: { tabs: AnalysisCreate['tabs'] } }>(
		'/v1/analysis/validate',
		{
			method: 'POST',
			body: JSON.stringify(data)
		}
	);

export const exportAnalysisCode = (
	analysisId: string,
	request: CodeExportRequest
): ResultAsync<CodeExportResponse, ApiError> =>
	apiRequest<CodeExportResponse>(`/v1/analysis/${analysisId}/export-code`, {
		method: 'POST',
		body: JSON.stringify(request)
	});
