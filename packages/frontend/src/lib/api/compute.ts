import type {
	EngineDefaults,
	EngineResourceConfig,
	EngineStatusResponse
} from '$lib/types/compute';
import type { AnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { createStream, type StreamHandle } from './websocket';
import { track } from '$lib/utils/audit-log';
import { computeActivityStore } from '$lib/stores/compute-activity.svelte';
import { isNamespaceReady, requireNamespace } from '$lib/stores/namespace.svelte';
import { shareInFlight } from './in-flight';

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

const previewInFlight = new Map<string, ResultAsync<StepPreviewResponse, ApiError>>();
const schemaInFlight = new Map<string, ResultAsync<StepSchemaResponse, ApiError>>();
const rowCountInFlight = new Map<string, ResultAsync<StepRowCountResponse, ApiError>>();
const spawnInFlight = new Map<string, ResultAsync<EngineStatusResponse, ApiError>>();
const configureInFlight = new Map<string, ResultAsync<EngineStatusResponse, ApiError>>();
const shutdownInFlight = new Map<string, ResultAsync<void, ApiError>>();

function namespaceKey(): string {
	if (!isNamespaceReady()) return '';
	return requireNamespace();
}

function requestKey(endpoint: string, body?: string): string {
	return `${namespaceKey()}:${endpoint}:${body ?? ''}`;
}

export function previewStepData(
	request: StepPreviewRequest
): ResultAsync<StepPreviewResponse, ApiError> {
	const body = JSON.stringify(request);
	return shareInFlight(previewInFlight, requestKey('/v1/compute/preview', body), () =>
		computeActivityStore.track(
			apiRequest<StepPreviewResponse>('/v1/compute/preview', {
				method: 'POST',
				body
			})
		)
	);
}

// Engine lifecycle functions

export function spawnEngine(
	analysisId: string,
	resourceConfig?: EngineResourceConfig
): ResultAsync<EngineStatusResponse, ApiError> {
	const body = resourceConfig ? JSON.stringify({ resource_config: resourceConfig }) : undefined;
	const endpoint = `/v1/compute/engine/spawn/${analysisId}`;
	return shareInFlight(spawnInFlight, requestKey(endpoint, body), () =>
		computeActivityStore.track(
			apiRequest<EngineStatusResponse>(endpoint, {
				method: 'POST',
				body
			})
		)
	);
}

export function configureEngine(
	analysisId: string,
	resourceConfig: EngineResourceConfig
): ResultAsync<EngineStatusResponse, ApiError> {
	const body = JSON.stringify(resourceConfig);
	const endpoint = `/v1/compute/engine/configure/${analysisId}`;
	return shareInFlight(configureInFlight, requestKey(endpoint, body), () =>
		computeActivityStore.track(
			apiRequest<EngineStatusResponse>(endpoint, {
				method: 'POST',
				body
			})
		)
	);
}

export function shutdownEngine(analysisId: string): ResultAsync<void, ApiError> {
	const endpoint = `/v1/compute/engine/${analysisId}`;
	return shareInFlight(shutdownInFlight, requestKey(endpoint), () =>
		computeActivityStore.track(
			apiRequest<void>(endpoint, {
				method: 'DELETE'
			})
		)
	);
}

export function shutdownEngineBestEffort(analysisId: string): void {
	shutdownEngine(analysisId).match(
		() => {},
		(error) => {
			if (error.status === 404 || error.status === 409) return;
			track({
				event: 'engine_error',
				action: 'teardown',
				target: analysisId,
				meta: { message: error.message, status: error.status }
			});
		}
	);
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
		return computeActivityStore
			.track(
				apiBlobRequest('/v1/compute/export', {
					method: 'POST',
					body: JSON.stringify(request)
				})
			)
			.andThen((blob) => {
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
	return computeActivityStore.track(
		apiRequest<ExportResponse>('/v1/compute/export', {
			method: 'POST',
			body: JSON.stringify(request)
		})
	);
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
	return computeActivityStore
		.track(
			apiBlobRequest('/v1/compute/download', {
				method: 'POST',
				body: JSON.stringify(request)
			})
		)
		.andThen((blob) => {
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
	const body = JSON.stringify(request);
	return shareInFlight(schemaInFlight, requestKey('/v1/compute/schema', body), () =>
		computeActivityStore.track(
			apiRequest<StepSchemaResponse>('/v1/compute/schema', {
				method: 'POST',
				body
			})
		)
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
	const body = JSON.stringify(request);
	return shareInFlight(rowCountInFlight, requestKey('/v1/compute/row-count', body), () =>
		computeActivityStore.track(
			apiRequest<StepRowCountResponse>('/v1/compute/row-count', {
				method: 'POST',
				body
			})
		)
	);
}

export interface CancelBuildResponse {
	build_id: string;
	engine_run_id: string | null;
	status: 'cancelled';
	duration_ms: number | null;
	cancelled_at: string;
	cancelled_by: string | null;
}

export interface BuildRequest {
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: string | null;
}

export type EnginesSnapshotMessage = {
	type: 'snapshot';
	engines: EngineStatusResponse[];
	total: number;
};
export type EnginesErrorMessage = { type: 'error'; error: string; status_code?: number };
export type EnginesStreamMessage = EnginesSnapshotMessage | EnginesErrorMessage;

export interface EnginesStreamCallbacks {
	onSnapshot: (engines: EngineStatusResponse[]) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

function parseEnginesStreamMessage(data: string): EnginesStreamMessage | null {
	try {
		return JSON.parse(data) as EnginesStreamMessage;
	} catch {
		return null;
	}
}

export function connectEnginesStream(callbacks: EnginesStreamCallbacks): StreamHandle {
	return createStream<EngineStatusResponse[]>('/v1/compute/ws/engines', {
		parse: parseEnginesStreamMessage,
		isSnapshot: (msg) => msg.type === 'snapshot',
		extractSnapshot: (msg) => (msg as EnginesSnapshotMessage).engines,
		callbacks
	});
}

export function cancelBuild(buildId: string): ResultAsync<CancelBuildResponse, ApiError> {
	return computeActivityStore.track(
		apiRequest<CancelBuildResponse>(`/v1/compute/builds/${buildId}/cancel`, {
			method: 'POST'
		})
	);
}
