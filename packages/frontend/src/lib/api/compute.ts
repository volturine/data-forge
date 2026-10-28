import type {
	ComputeWorkerDefaults,
	ComputeWorkerResourceConfig,
	ComputeWorkerScope,
	ComputeWorkerStatusResponse,
	Field,
	NumberField,
	StringField
} from '#lib/types/compute.js';
import type {
	DownloadCommandJson as ProtocolDownloadCommandJson,
	StepPreviewCommandJson as ProtocolStepPreviewCommandJson,
	StepPreviewResultJson as ProtocolStepPreviewResultJson,
	StepRowCountResultJson as ProtocolStepRowCountResultJson,
	StepSchemaCommandJson as ProtocolStepSchemaCommandJson,
	StepSchemaResultJson as ProtocolStepSchemaResultJson
} from '#lib/protocol/dataforge_protocol/compute_pb.js';
import type { ExportFormat } from '#lib/types/protocol-enum-tokens.js';
import type { AnalysisPipelinePayload } from '#lib/utils/analysis-pipeline.js';
import { apiBlobRequest, apiRequest } from './client';
import { okAsync, ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { createStream, type StreamHandle } from './websocket';
import { computeActivityStore } from '#lib/stores/compute-activity.svelte.js';
import {
	namespaceKey,
	shareInFlight,
	shareInFlightWithSignal,
	type SharedInFlight
} from './in-flight';

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
	resource_config?: ComputeWorkerResourceConfig | null;
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

interface ComputeInFlight<T> {
	shared: Map<string, ResultAsync<T, ApiError>>;
	owned: Map<string, SharedInFlight<T, ApiError>>;
}

function createComputeInFlight<T>(): ComputeInFlight<T> {
	return { shared: new Map(), owned: new Map() };
}

const previewInFlight = createComputeInFlight<StepPreviewResponse>();
const schemaInFlight = createComputeInFlight<StepSchemaResponse>();
const rowCountInFlight = createComputeInFlight<StepRowCountResponse>();
const shutdownInFlight = new Map<string, ResultAsync<void, ApiError>>();

export interface ComputeRequestOptions {
	signal?: AbortSignal;
}

function cancelledComputeError(): ApiError {
	return { type: 'network', message: 'Compute request cancelled' };
}

function requestKey(endpoint: string, body?: string): string {
	return `${namespaceKey()}:${endpoint}:${body ?? ''}`;
}

function sharedComputePost<T>(
	endpoint: string,
	request: unknown,
	inFlight: ComputeInFlight<T>,
	options?: ComputeRequestOptions
): ResultAsync<T, ApiError> {
	const body = JSON.stringify(request);
	const key = requestKey(endpoint, body);
	const send = (signal?: AbortSignal): ResultAsync<T, ApiError> =>
		computeActivityStore.track(apiRequest<T>(endpoint, { method: 'POST', body, signal }));
	if (!options?.signal) return shareInFlight(inFlight.shared, key, () => send());
	return shareInFlightWithSignal(inFlight.owned, key, send, options.signal, cancelledComputeError);
}

export function previewStepData(
	request: StepPreviewRequest,
	options?: ComputeRequestOptions
): ResultAsync<StepPreviewResponse, ApiError> {
	return sharedComputePost('/v1/compute/preview', request, previewInFlight, options);
}

// Compute worker lifecycle functions

export function shutdownComputeWorkerByIdentity(
	scope: ComputeWorkerScope,
	resourceId: string
): ResultAsync<void, ApiError> {
	const segment =
		scope === 'datasource_preview'
			? 'datasource-preview'
			: scope === 'build'
				? 'build'
				: 'analysis';
	const endpoint = `/v1/compute/compute-worker/${segment}/${resourceId}`;
	return shareInFlight(shutdownInFlight, requestKey(endpoint), () =>
		computeActivityStore.track(
			apiRequest<void>(endpoint, {
				method: 'DELETE'
			})
		)
	);
}

export function getComputeWorkerDefaults(
	options?: ComputeRequestOptions
): ResultAsync<ComputeWorkerDefaults, ApiError> {
	return apiRequest<ComputeWorkerDefaults>(
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
	return sharedComputePost('/v1/compute/schema', request, schemaInFlight, options);
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
	return sharedComputePost('/v1/compute/row-count', request, rowCountInFlight, options);
}

export function throwIfAborted(signal: AbortSignal): void {
	if (!signal.aborted) return;
	const error = new Error('Compute request cancelled');
	error.name = 'AbortError';
	throw error;
}

export interface CancelBuildResponse {
	build_id: string;
	compute_worker_run_id: string | null;
	status: 'cancelled';
	duration_ms: number | null;
	cancelled_at: string;
	cancelled_by: string | null;
}

export interface BuildRequest {
	analysis_pipeline: AnalysisPipelinePayload;
	tab_id: string;
}

export type ComputeWorkersSnapshotMessage = {
	type: 'snapshot';
	compute_workers: ComputeWorkerStatusResponse[];
	total: number;
};
export type ComputeWorkersErrorMessage = { type: 'error'; error: string; status_code?: number };
export type ComputeWorkersStreamMessage =
	ComputeWorkersSnapshotMessage | ComputeWorkersErrorMessage;

export interface ComputeWorkersStreamCallbacks {
	onSnapshot: (computeWorkers: ComputeWorkerStatusResponse[]) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

function parseComputeWorkersStreamMessage(data: string): ComputeWorkersStreamMessage | null {
	try {
		return JSON.parse(data) as ComputeWorkersStreamMessage;
	} catch {
		return null;
	}
}

export function connectComputeWorkersStream(
	callbacks: ComputeWorkersStreamCallbacks
): StreamHandle {
	return createStream('/v1/compute/ws/compute-workers', {
		parse: parseComputeWorkersStreamMessage,
		isSnapshot: (msg): msg is ComputeWorkersSnapshotMessage => msg.type === 'snapshot',
		extractSnapshot: (msg) => msg.compute_workers,
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
