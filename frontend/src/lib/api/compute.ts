import type {
	EngineDefaults,
	EngineListResponse,
	EngineResourceConfig,
	EngineStatusResponse
} from '$lib/types/compute';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

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
	resource_config?: EngineResourceConfig | null;
	datasource_config?: Record<string, unknown> | null;
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
}

export function previewStepData(
	request: StepPreviewRequest
): ResultAsync<StepPreviewResponse, ApiError> {
	return apiRequest<StepPreviewResponse>('/v1/compute/preview', {
		method: 'POST',
		body: JSON.stringify(request)
	});
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
	datasource_id: string;
	pipeline_steps: Array<{
		id: string;
		type: string;
		config: Record<string, unknown>;
		depends_on?: string[];
	}>;
	target_step_id: string;
	format?: 'csv' | 'parquet' | 'json' | 'ndjson' | 'duckdb';
	filename?: string;
	destination: 'download' | 'filesystem' | 'datasource';
	datasource_type?: 'iceberg' | 'duckdb' | 'file';
	iceberg_options?: {
		table_name?: string;
		namespace?: string;
	};
	duckdb_options?: {
		table_name?: string;
	};
	datasource_config?: Record<string, unknown> | null;
	output_datasource_id?: string | null;
}

export interface ExportResponse {
	success: boolean;
	filename: string;
	format: string;
	destination: string;
	file_path: string | null;
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
			if (request.format) {
				const ext = request.format.startsWith('.') ? request.format : `.${request.format}`;
				downloadBlob(blob, `${filename}${ext}`);
				return okAsync(blob);
			}
			downloadBlob(blob, filename);
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
	datasource_config?: Record<string, unknown> | null;
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

export function buildAnalysis(
	analysisId: string,
	tabId?: string
): ResultAsync<BuildResponse, ApiError> {
	const params = tabId ? `?tab_id=${encodeURIComponent(tabId)}` : '';
	return apiRequest<BuildResponse>(`/v1/compute/build/${analysisId}${params}`, {
		method: 'POST'
	});
}
