import type {
	Analysis,
	AnalysisCreate,
	AnalysisGalleryItem,
	AnalysisUpdate
} from '$lib/types/analysis';
import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export function createAnalysis(data: AnalysisCreate): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>('/api/v1/analysis', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function listAnalyses(): ResultAsync<AnalysisGalleryItem[], ApiError> {
	return apiRequest<AnalysisGalleryItem[]>('/api/v1/analysis');
}

export function getAnalysis(id: string): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>(`/api/v1/analysis/${id}`);
}

export function updateAnalysis(id: string, data: AnalysisUpdate): ResultAsync<Analysis, ApiError> {
	return apiRequest<Analysis>(`/api/v1/analysis/${id}`, {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export function deleteAnalysis(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/api/v1/analysis/${id}`, {
		method: 'DELETE'
	});
}
