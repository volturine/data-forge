import type {
	Analysis,
	AnalysisCreate,
	AnalysisGalleryItem,
	AnalysisUpdate
} from '$lib/types/analysis';
import { apiRequest } from './client';

export async function createAnalysis(data: AnalysisCreate): Promise<Analysis> {
	return apiRequest<Analysis>('/api/v1/analysis', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export async function listAnalyses(): Promise<AnalysisGalleryItem[]> {
	return apiRequest<AnalysisGalleryItem[]>('/api/v1/analysis');
}

export async function getAnalysis(id: string): Promise<Analysis> {
	return apiRequest<Analysis>(`/api/v1/analysis/${id}`);
}

export async function updateAnalysis(id: string, data: AnalysisUpdate): Promise<Analysis> {
	return apiRequest<Analysis>(`/api/v1/analysis/${id}`, {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export async function deleteAnalysis(id: string): Promise<void> {
	await apiRequest<void>(`/api/v1/analysis/${id}`, {
		method: 'DELETE'
	});
}
