import type {
	EngineDefaults,
	EngineIdentityPayload,
	EngineResourceConfig,
	EngineScope,
	EngineStatusResponse
} from '$lib/types/compute';
import type {
	DownloadCommandJson as ProtocolDownloadCommandJson,
	ExportCommandJson as ProtocolExportCommandJson,
	ExportResultJson as ProtocolExportResultJson,
	IcebergExportOptionsJson as ProtocolIcebergExportOptionsJson,
	StepPreviewCommandJson as ProtocolStepPreviewCommandJson,
	StepPreviewResultJson as ProtocolStepPreviewResultJson,
	StepRowCountResultJson as ProtocolStepRowCountResultJson,
	StepSchemaCommandJson as ProtocolStepSchemaCommandJson,
	StepSchemaResultJson as ProtocolStepSchemaResultJson
} from '$lib/protocol/dataforge_protocol/compute_pb';
import type { ExportDestination, ExportFormat } from '$lib/types/protocol-enum-tokens';
import type { AnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { createStream, type StreamHandle } from './websocket';
import { track } from '$lib/utils/audit-log';
import { computeActivityStore } from '$lib/stores/compute-activity.svelte';
import { isNamespaceReady, requireNamespace } from '$lib/stores/namespace.svelte';
import { shareInFlight } from './in-flight';

type Field<T, K extends keyof T> = NonNullable<T[K]>;
type StringField<T, K extends keyof T> = Extract<Field<T, K>, string>;
type NumberField<T, K extends keyof T> = Extract<Field<T, K>, number>;
type OptionalStringField<T, K extends keyof T> = StringField<T, K> | null;
type StructHttpField<T, K extends keyof T> =
	Field<T, K> extends Record<string, unknown> ? Record<string, unknown> : never;
type StructArrayHttpField<T, K extends keyof T> =
	Field<T, K> extends unknown[] ? Array<Record<string, unknown>> : never;
type Int64HttpNumber<T, K extends keyof T> = Field<T, K> extends string ? number : never;

export interface StepPreviewRequest {
	analysis_id?: OptionalStringField<ProtocolStepPreviewCommandJson, 'analysisId'>;
	engine_identity?: EngineIdentityPayload | null;
	target_step_id: StringField<ProtocolStepPreviewCommandJson, 'targetStepId'>;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: OptionalStringField<ProtocolStepPreviewCommandJson, 'tabId'>;
	row_limit?: NumberField<ProtocolStepPreviewCommandJson, 'rowLimit'>;
	page?: NumberField<ProtocolStepPreviewCommandJson, 'page'>;
	resource_config?: EngineResourceConfig | null;
}

export type StepPreviewResourceConfig = StepPreviewRequest['resource_config'];

export interface StepPreviewResponse {
	step_id: StringField<ProtocolStepPreviewResultJson, 'stepId'>;
	columns: Field<ProtocolStepPreviewResultJson, 'columns'>;
	column_types?: Field<ProtocolStepPreviewResultJson, 'columnTypes'>;
	data: StructArrayHttpField<ProtocolStepPreviewResultJson, 'rows'>;
	total_rows: NumberField<ProtocolStepPreviewResultJson, 'totalRows'>;
	page: NumberField<ProtocolStepPreviewResultJson, 'page'>;
	page_size: NumberField<ProtocolStepPreviewResultJson, 'pageSize'>;
	metadata?: StructHttpField<ProtocolStepPreviewResultJson, 'metadata'>;
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

export function spawnAnalysisEngine(
	analysisId: string,
	resourceConfig?: EngineResourceConfig
): ResultAsync<EngineStatusResponse, ApiError> {
	const body = resourceConfig ? JSON.stringify({ resource_config: resourceConfig }) : undefined;
	const endpoint = `/v1/compute/engine/spawn/analysis/${analysisId}`;
	return shareInFlight(spawnInFlight, requestKey(endpoint, body), () =>
		computeActivityStore.track(
			apiRequest<EngineStatusResponse>(endpoint, {
				method: 'POST',
				body
			})
		)
	);
}

export function configureAnalysisEngine(
	analysisId: string,
	resourceConfig: EngineResourceConfig
): ResultAsync<EngineStatusResponse, ApiError> {
	const body = JSON.stringify(resourceConfig);
	const endpoint = `/v1/compute/engine/configure/analysis/${analysisId}`;
	return shareInFlight(configureInFlight, requestKey(endpoint, body), () =>
		computeActivityStore.track(
			apiRequest<EngineStatusResponse>(endpoint, {
				method: 'POST',
				body
			})
		)
	);
}

export function shutdownAnalysisEngine(analysisId: string): ResultAsync<void, ApiError> {
	const endpoint = `/v1/compute/engine/analysis/${analysisId}`;
	return shareInFlight(shutdownInFlight, requestKey(endpoint), () =>
		computeActivityStore.track(
			apiRequest<void>(endpoint, {
				method: 'DELETE'
			})
		)
	);
}

export function shutdownEngineByIdentity(
	scope: EngineScope,
	resourceId: string
): ResultAsync<void, ApiError> {
	const segment =
		scope === 'datasource_preview'
			? 'datasource-preview'
			: scope === 'build'
				? 'build'
				: 'analysis';
	const endpoint = `/v1/compute/engine/${segment}/${resourceId}`;
	return shareInFlight(shutdownInFlight, requestKey(endpoint), () =>
		computeActivityStore.track(
			apiRequest<void>(endpoint, {
				method: 'DELETE'
			})
		)
	);
}

export function shutdownEngineBestEffort(analysisId: string): void {
	shutdownAnalysisEngine(analysisId).match(
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
	analysis_id?: OptionalStringField<ProtocolExportCommandJson, 'analysisId'>;
	target_step_id: StringField<ProtocolExportCommandJson, 'targetStepId'>;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: OptionalStringField<ProtocolExportCommandJson, 'tabId'>;
	format?: ExportFormat;
	filename?: StringField<ProtocolExportCommandJson, 'filename'>;
	destination: ExportDestination;
	iceberg_options?: {
		table_name?: StringField<ProtocolIcebergExportOptionsJson, 'tableName'>;
		namespace?: StringField<ProtocolIcebergExportOptionsJson, 'namespace'>;
		branch: StringField<ProtocolIcebergExportOptionsJson, 'branch'>;
	};
	result_id: StringField<ProtocolExportCommandJson, 'resultId'>;
}

export interface ExportResponse {
	success: Field<ProtocolExportResultJson, 'success'>;
	filename: StringField<ProtocolExportResultJson, 'filename'>;
	format: ExportFormat;
	destination: ExportDestination;
	message: OptionalStringField<ProtocolExportResultJson, 'message'>;
	datasource_id: OptionalStringField<ProtocolExportResultJson, 'datasourceId'>;
	datasource_name?: OptionalStringField<ProtocolExportResultJson, 'datasourceName'>;
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
	analysis_id?: OptionalStringField<ProtocolDownloadCommandJson, 'analysisId'>;
	target_step_id: StringField<ProtocolDownloadCommandJson, 'targetStepId'>;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: OptionalStringField<ProtocolDownloadCommandJson, 'tabId'>;
	format?: ExportFormat;
	filename?: StringField<ProtocolDownloadCommandJson, 'filename'>;
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
	analysis_id?: OptionalStringField<ProtocolStepSchemaCommandJson, 'analysisId'>;
	target_step_id: StringField<ProtocolStepSchemaCommandJson, 'targetStepId'>;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: OptionalStringField<ProtocolStepSchemaCommandJson, 'tabId'>;
}

export interface StepSchemaResponse {
	step_id: StringField<ProtocolStepSchemaResultJson, 'stepId'>;
	columns: Field<ProtocolStepSchemaResultJson, 'columns'>;
	column_types: Field<ProtocolStepSchemaResultJson, 'columnTypes'>;
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
	step_id: StringField<ProtocolStepRowCountResultJson, 'stepId'>;
	row_count: Int64HttpNumber<ProtocolStepRowCountResultJson, 'rowCount'>;
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
