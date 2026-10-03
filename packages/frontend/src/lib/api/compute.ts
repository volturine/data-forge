import type {
	EngineDefaults,
	EngineResourceConfig,
	EngineScope,
	EngineStatusResponse
} from '$lib/types/compute';
import type {
	DownloadCommandJson as ProtocolDownloadCommandJson,
	StepPreviewCommandJson as ProtocolStepPreviewCommandJson,
	StepPreviewResultJson as ProtocolStepPreviewResultJson,
	StepRowCountResultJson as ProtocolStepRowCountResultJson,
	StepSchemaCommandJson as ProtocolStepSchemaCommandJson,
	StepSchemaResultJson as ProtocolStepSchemaResultJson
} from '$lib/protocol/dataforge_protocol/compute_pb';
import type { ExportFormat } from '$lib/types/protocol-enum-tokens';
import type { AnalysisPipelinePayload } from '$lib/utils/analysis-pipeline';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { createStream, type StreamHandle } from './websocket';
import { computeActivityStore } from '$lib/stores/compute-activity.svelte';
import { isNamespaceReady, requireNamespace } from '$lib/stores/namespace.svelte';
import { shareInFlight, shareInFlightWithSignal, type SharedInFlight } from './in-flight';

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
	datasource_id?: string | null;
	target_step_id: StringField<ProtocolStepPreviewCommandJson, 'targetStepId'>;
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id?: OptionalStringField<ProtocolStepPreviewCommandJson, 'tabId'>;
	row_limit?: NumberField<ProtocolStepPreviewCommandJson, 'rowLimit'>;
	page?: NumberField<ProtocolStepPreviewCommandJson, 'page'>;
	resource_config?: EngineResourceConfig | null;
}

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
const previewSignalInFlight = new Map<string, SharedInFlight<StepPreviewResponse, ApiError>>();
const schemaInFlight = new Map<string, ResultAsync<StepSchemaResponse, ApiError>>();
const schemaSignalInFlight = new Map<string, SharedInFlight<StepSchemaResponse, ApiError>>();
const rowCountInFlight = new Map<string, ResultAsync<StepRowCountResponse, ApiError>>();
const rowCountSignalInFlight = new Map<string, SharedInFlight<StepRowCountResponse, ApiError>>();
const spawnInFlight = new Map<string, ResultAsync<EngineStatusResponse, ApiError>>();
const shutdownInFlight = new Map<string, ResultAsync<void, ApiError>>();

export interface ComputeRequestOptions {
	signal?: AbortSignal;
}

function cancelledComputeError(): ApiError {
	return { type: 'network', message: 'Compute request cancelled' };
}

function namespaceKey(): string {
	if (!isNamespaceReady()) return '';
	return requireNamespace();
}

function requestKey(endpoint: string, body?: string): string {
	return `${namespaceKey()}:${endpoint}:${body ?? ''}`;
}

export function previewStepData(
	request: StepPreviewRequest,
	options?: ComputeRequestOptions
): ResultAsync<StepPreviewResponse, ApiError> {
	const body = JSON.stringify(request);
	const key = requestKey('/v1/compute/preview', body);
	const factory = (signal?: AbortSignal) =>
		computeActivityStore.track(
			apiRequest<StepPreviewResponse>('/v1/compute/preview', {
				method: 'POST',
				body,
				...(signal ? { signal } : {})
			})
		);
	if (!options?.signal) return shareInFlight(previewInFlight, key, () => factory());
	return shareInFlightWithSignal(
		previewSignalInFlight,
		key,
		(signal) => factory(signal),
		options.signal,
		cancelledComputeError
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

export function getEngineDefaults(
	options?: ComputeRequestOptions
): ResultAsync<EngineDefaults, ApiError> {
	return apiRequest<EngineDefaults>(
		'/v1/compute/defaults',
		options?.signal ? { signal: options.signal } : undefined
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
	request: StepSchemaRequest,
	options?: ComputeRequestOptions
): ResultAsync<StepSchemaResponse, ApiError> {
	const body = JSON.stringify(request);
	const factory = (signal?: AbortSignal) =>
		computeActivityStore.track(
			apiRequest<StepSchemaResponse>('/v1/compute/schema', {
				method: 'POST',
				body,
				...(signal ? { signal } : {})
			})
		);
	const key = requestKey('/v1/compute/schema', body);
	if (!options?.signal) return shareInFlight(schemaInFlight, key, () => factory());
	return shareInFlightWithSignal(
		schemaSignalInFlight,
		key,
		(signal) => factory(signal),
		options.signal,
		cancelledComputeError
	);
}

export type StepRowCountRequest = StepSchemaRequest;

export interface StepRowCountResponse {
	step_id: StringField<ProtocolStepRowCountResultJson, 'stepId'>;
	row_count: Int64HttpNumber<ProtocolStepRowCountResultJson, 'rowCount'>;
}

export function getStepRowCount(
	request: StepRowCountRequest,
	options?: ComputeRequestOptions
): ResultAsync<StepRowCountResponse, ApiError> {
	const body = JSON.stringify(request);
	const factory = (signal?: AbortSignal) =>
		computeActivityStore.track(
			apiRequest<StepRowCountResponse>('/v1/compute/row-count', {
				method: 'POST',
				body,
				...(signal ? { signal } : {})
			})
		);
	const key = requestKey('/v1/compute/row-count', body);
	if (!options?.signal) return shareInFlight(rowCountInFlight, key, () => factory());
	return shareInFlightWithSignal(
		rowCountSignalInFlight,
		key,
		(signal) => factory(signal),
		options.signal,
		cancelledComputeError
	);
}

export function throwIfAborted(signal: AbortSignal): void {
	if (!signal.aborted) return;
	const error = new Error('Compute request cancelled');
	error.name = 'AbortError';
	throw error;
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
	tab_id: string;
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
