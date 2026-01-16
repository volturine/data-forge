import type { ComputeJob, ComputeStatus } from '$lib/types/compute';
import type { RawComputeJobResponse } from '$lib/types/api-responses';
import { apiRequest } from './client';

export interface PreviewResponse {
	columns: string[];
	data: Record<string, unknown>[];
	total_count: number;
}

function isValidComputeStatus(status: unknown): status is ComputeStatus {
	return (
		status === 'pending' || status === 'running' || status === 'completed' || status === 'failed'
	);
}

function normalizeJob(raw: RawComputeJobResponse): ComputeJob {
	const status: ComputeStatus = isValidComputeStatus(raw.status) ? raw.status : 'pending';

	return {
		id: raw.job_id ?? raw.id ?? '',
		status,
		progress: raw.progress ?? 0,
		error: raw.error_message ?? raw.error ?? null,
		result: raw.data ?? raw.result,
		created_at: raw.created_at ?? '',
		updated_at: raw.updated_at ?? ''
	};
}

export async function executeAnalysis(analysisId: string): Promise<ComputeJob> {
	const raw = await apiRequest<RawComputeJobResponse>('/api/v1/compute/execute', {
		method: 'POST',
		body: JSON.stringify({
			analysis_id: analysisId,
			execute_mode: 'full',
			step_id: null
		})
	});
	return normalizeJob(raw);
}

export async function getComputeStatus(jobId: string): Promise<ComputeJob> {
	const raw = await apiRequest<RawComputeJobResponse>(`/api/v1/compute/status/${jobId}`);
	return normalizeJob(raw);
}

export async function previewStep(analysisId: string, stepId: string): Promise<PreviewResponse> {
	return apiRequest<PreviewResponse>('/api/v1/compute/preview', {
		method: 'POST',
		body: JSON.stringify({
			analysis_id: analysisId,
			execute_mode: 'preview',
			step_id: stepId
		})
	});
}

export async function cancelJob(jobId: string): Promise<void> {
	await apiRequest<void>(`/api/v1/compute/${jobId}`, {
		method: 'DELETE'
	});
}

export async function cleanupJob(jobId: string): Promise<void> {
	await apiRequest<void>(`/api/v1/compute/${jobId}/cleanup`, {
		method: 'DELETE'
	});
}
