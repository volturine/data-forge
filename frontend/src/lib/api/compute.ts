import type {
	EngineDefaults,
	EngineListResponse,
	EngineResourceConfig,
	EngineStatusResponse
} from '$lib/types/compute';
import type { AnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { websocketRequest } from './websocket';

export interface StepPreviewRequest {
	analysis_id?: string;
	target_step_id: string;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: string | null;
	row_limit?: number;
	page?: number;
	resource_config?: EngineResourceConfig | null;
}

export type StepPreviewResourceConfig = StepPreviewRequest['resource_config'];

export interface StepPreviewResponse {
	step_id: string;
	columns: string[];
	column_types?: Record<string, string>;
	data: Array<Record<string, unknown>>;
	total_rows: number;
	page: number;
	page_size: number;
	metadata?: Record<string, unknown>;
}

export function previewStepData(
	request: StepPreviewRequest
): ResultAsync<StepPreviewResponse, ApiError> {
	return websocketRequest('/v1/compute/ws', 'preview', request, () =>
		apiRequest<StepPreviewResponse>('/v1/compute/preview', {
			method: 'POST',
			body: JSON.stringify(request)
		})
	);
}

// Engine lifecycle functions

export function spawnEngine(
	analysisId: string,
	resourceConfig?: EngineResourceConfig
): ResultAsync<EngineStatusResponse, ApiError> {
	const body = resourceConfig ? JSON.stringify({ resource_config: resourceConfig }) : undefined;
	return apiRequest<EngineStatusResponse>(`/v1/compute/engine/spawn/${analysisId}`, {
		method: 'POST',
		body
	});
}

export function configureEngine(
	analysisId: string,
	resourceConfig: EngineResourceConfig
): ResultAsync<EngineStatusResponse, ApiError> {
	return apiRequest<EngineStatusResponse>(`/v1/compute/engine/configure/${analysisId}`, {
		method: 'POST',
		body: JSON.stringify(resourceConfig)
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

export function getEngineDefaults(): ResultAsync<EngineDefaults, ApiError> {
	return apiRequest<EngineDefaults>('/v1/compute/defaults');
}

export interface ExportRequest {
	analysis_id?: string;
	target_step_id: string;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: string | null;
	format?: 'csv' | 'parquet' | 'json' | 'ndjson' | 'duckdb';
	filename?: string;
	destination: 'download' | 'datasource';
	iceberg_options?: {
		table_name?: string;
		namespace?: string;
		branch: string;
	};
	result_id: string;
}

export interface ExportResponse {
	success: boolean;
	filename: string;
	format: string;
	destination: string;
	message: string | null;
	datasource_id: string | null;
	datasource_name?: string | null;
}

export function exportData(request: ExportRequest): ResultAsync<Blob | ExportResponse, ApiError> {
	if (request.destination === 'download') {
		return apiBlobRequest('/v1/compute/export', {
			method: 'POST',
			body: JSON.stringify(request)
		}).andThen((blob) => {
			const filename = request.filename ?? 'export';
			const ext = request.format
				? request.format.startsWith('.')
					? request.format
					: `.${request.format}`
				: '';
			downloadBlob(blob, `${filename}${ext}`);
			return okAsync(blob);
		});
	}
	return apiRequest<ExportResponse>('/v1/compute/export', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}

export interface DownloadRequest {
	analysis_id?: string;
	target_step_id: string;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: string | null;
	format?: 'csv' | 'parquet' | 'json' | 'ndjson' | 'excel' | 'duckdb';
	filename?: string;
}

export function downloadStep(request: DownloadRequest): ResultAsync<Blob, ApiError> {
	return apiBlobRequest('/v1/compute/download', {
		method: 'POST',
		body: JSON.stringify(request)
	}).andThen((blob) => {
		const filename = request.filename ?? 'download';
		const format = request.format ?? 'csv';
		const ext = format.startsWith('.') ? format : `.${format}`;
		downloadBlob(blob, `${filename}${ext}`);
		return okAsync(blob);
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
	analysis_id?: string;
	target_step_id: string;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: string | null;
}

export interface StepSchemaResponse {
	step_id: string;
	columns: string[];
	column_types: Record<string, string>;
}

export function getStepSchema(
	request: StepSchemaRequest
): ResultAsync<StepSchemaResponse, ApiError> {
	return websocketRequest('/v1/compute/ws', 'schema', request, () =>
		apiRequest<StepSchemaResponse>('/v1/compute/schema', {
			method: 'POST',
			body: JSON.stringify(request)
		})
	);
}

export type StepRowCountRequest = StepSchemaRequest;

export interface StepRowCountResponse {
	step_id: string;
	row_count: number;
}

export function getStepRowCount(
	request: StepRowCountRequest
): ResultAsync<StepRowCountResponse, ApiError> {
	return websocketRequest('/v1/compute/ws', 'row_count', request, () =>
		apiRequest<StepRowCountResponse>('/v1/compute/row-count', {
			method: 'POST',
			body: JSON.stringify(request)
		})
	);
}

export interface BuildTabResult {
	tab_id: string;
	tab_name: string;
	status: string;
	error?: string | null;
}

export interface BuildResponse {
	analysis_id: string;
	tabs_built: number;
	results: BuildTabResult[];
}

export interface BuildRequest {
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: string | null;
}

export function buildAnalysisWithPayload(
	request: BuildRequest
): ResultAsync<BuildResponse, ApiError> {
	return websocketRequest('/v1/compute/ws', 'build', request, () =>
		apiRequest<BuildResponse>('/v1/compute/build', {
			method: 'POST',
			body: JSON.stringify(request)
		})
	);
}
