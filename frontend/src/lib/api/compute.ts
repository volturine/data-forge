import type {
	ComputeJob,
	ComputeStatus,
	EngineListResponse,
	EngineStatusResponse
} from '$lib/types/compute';
import type { RawComputeJobResponse } from '$lib/types/api-responses';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export interface PreviewResponse {
	columns: string[];
	data: Record<string, unknown>[];
	total_count: number;
}

export interface StepPreviewRequest {
	analysis_id: string;
	datasource_id: string;
	pipeline_steps: Array<{
		id: string;
		type: string;
		config: Record<string, unknown>;
		depends_on?: string[];
	}>;
	target_step_id: string;
	row_limit?: number;
	page?: number;
}

export interface StepPreviewResponse {
	step_id: string;
	columns: string[];
	column_types?: Record<string, string>;
	data: Array<Record<string, unknown>>;
	total_rows: number;
	page: number;
	page_size: number;
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

export function executeAnalysis(analysisId: string): ResultAsync<ComputeJob, ApiError> {
	return apiRequest<RawComputeJobResponse>('/v1/compute/execute', {
		method: 'POST',
		body: JSON.stringify({
			analysis_id: analysisId,
			execute_mode: 'full',
			step_id: null
		})
	}).map(normalizeJob);
}

export function getComputeStatus(jobId: string): ResultAsync<ComputeJob, ApiError> {
	return apiRequest<RawComputeJobResponse>(`/v1/compute/status/${jobId}`).map(normalizeJob);
}

export function previewStep(
	analysisId: string,
	stepId: string
): ResultAsync<PreviewResponse, ApiError> {
	return apiRequest<PreviewResponse>('/v1/compute/preview', {
		method: 'POST',
		body: JSON.stringify({
			analysis_id: analysisId,
			execute_mode: 'preview',
			step_id: stepId
		})
	});
}

export function previewStepData(
	request: StepPreviewRequest
): ResultAsync<StepPreviewResponse, ApiError> {
	return apiRequest<StepPreviewResponse>('/v1/compute/preview', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}

export function cancelJob(jobId: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/compute/${jobId}`, {
		method: 'DELETE'
	});
}

export function cleanupJob(jobId: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/compute/${jobId}/cleanup`, {
		method: 'DELETE'
	});
}

// Engine lifecycle functions

export function spawnEngine(analysisId: string): ResultAsync<EngineStatusResponse, ApiError> {
	return apiRequest<EngineStatusResponse>(`/v1/compute/engine/spawn/${analysisId}`, {
		method: 'POST'
	});
}

export function sendKeepalive(analysisId: string): ResultAsync<EngineStatusResponse, ApiError> {
	return apiRequest<EngineStatusResponse>(`/v1/compute/engine/keepalive/${analysisId}`, {
		method: 'POST'
	});
}

export function getEngineStatus(analysisId: string): ResultAsync<EngineStatusResponse, ApiError> {
	return apiRequest<EngineStatusResponse>(`/v1/compute/engine/status/${analysisId}`);
}

export function shutdownEngine(analysisId: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/compute/engine/${analysisId}`, {
		method: 'DELETE'
	});
}

export function listEngines(): ResultAsync<EngineListResponse, ApiError> {
	return apiRequest<EngineListResponse>('/v1/compute/engines');
}

export interface ExportRequest {
	analysis_id?: string;
	datasource_id: string;
	pipeline_steps: Array<{
		id: string;
		type: string;
		config: Record<string, unknown>;
		depends_on?: string[];
	}>;
	target_step_id: string;
	format: 'csv' | 'parquet' | 'json' | 'ndjson';
	filename: string;
	destination: 'download' | 'filesystem';
}

export interface ExportResponse {
	success: boolean;
	filename: string;
	format: string;
	destination: string;
	file_path: string | null;
	message: string | null;
}

export function exportData(request: ExportRequest): ResultAsync<Blob | ExportResponse, ApiError> {
	if (request.destination === 'download') {
		return apiBlobRequest('/v1/compute/export', {
			method: 'POST',
			body: JSON.stringify(request)
		}).andThen((blob) => {
			const ext = request.format.startsWith('.') ? request.format : `.${request.format}`;
			downloadBlob(blob, `${request.filename}${ext}`);
			return okAsync(blob);
		});
	}
	return apiRequest<ExportResponse>('/v1/compute/export', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}

export function downloadBlob(blob: Blob, filename: string): void {
	const url = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(url);
}

export interface StepSchemaRequest {
	analysis_id: string;
	datasource_id: string;
	pipeline_steps: Array<{
		id: string;
		type: string;
		config: Record<string, unknown>;
		depends_on?: string[];
	}>;
	target_step_id: string;
}

export interface StepSchemaResponse {
	step_id: string;
	columns: string[];
	column_types: Record<string, string>;
}

export function getStepSchema(
	request: StepSchemaRequest
): ResultAsync<StepSchemaResponse, ApiError> {
	return apiRequest<StepSchemaResponse>('/v1/compute/schema', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}
