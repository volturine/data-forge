import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { buildWebsocketUrl } from './websocket';

export interface EngineRunExecutionEntry {
	key: string;
	label: string;
	category: 'read' | 'step' | 'plan' | 'write';
	order: number;
	duration_ms: number | null;
	share_pct: number | null;
	optimized_plan: string | null;
	unoptimized_plan: string | null;
	metadata: Record<string, unknown> | null;
}

export interface EngineRun {
	id: string;
	analysis_id: string | null;
	datasource_id: string;
	kind: string;
	status: 'running' | 'success' | 'failed';
	request_json: Record<string, unknown>;
	result_json: Record<string, unknown> | null;
	error_message: string | null;
	created_at: string;
	completed_at: string | null;
	duration_ms: number | null;
	step_timings: Record<string, number>;
	query_plan: string | null;
	progress: number;
	current_step: string | null;
	triggered_by: string | null;
	execution_entries: EngineRunExecutionEntry[];
}

export interface ColumnDiff {
	column: string;
	status: 'added' | 'removed' | 'type_changed';
	type_a: string | null;
	type_b: string | null;
}

export interface TimingDiff {
	step: string;
	ms_a: number | null;
	ms_b: number | null;
	delta_ms: number | null;
	delta_pct: number | null;
}

export interface RunSummary {
	id: string;
	kind: string;
	status: string;
	created_at: string;
	duration_ms: number | null;
	row_count: number | null;
	schema_columns: number;
	triggered_by: string | null;
}

export interface BuildComparison {
	run_a: RunSummary;
	run_b: RunSummary;
	row_count_a: number | null;
	row_count_b: number | null;
	row_count_delta: number | null;
	schema_diff: ColumnDiff[];
	timing_diff: TimingDiff[];
	total_duration_delta_ms: number | null;
}

export interface ListEngineRunsParams {
	analysis_id?: string;
	datasource_id?: string;
	kind?: string;
	status?: 'running' | 'success' | 'failed';
	limit?: number;
	offset?: number;
}

export function listEngineRuns(params?: ListEngineRunsParams): ResultAsync<EngineRun[], ApiError> {
	const query = new URLSearchParams();
	if (params?.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params?.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params?.kind) query.set('kind', params.kind);
	if (params?.status) query.set('status', params.status);
	if (params?.limit !== undefined) query.set('limit', String(params.limit));
	if (params?.offset !== undefined) query.set('offset', String(params.offset));
	const suffix = query.toString() ? `?${query.toString()}` : '';
	return apiRequest<EngineRun[]>(`/v1/engine-runs${suffix}`);
}

export function getEngineRun(id: string): ResultAsync<EngineRun, ApiError> {
	return apiRequest<EngineRun>(`/v1/engine-runs/${id}`);
}

export function compareEngineRuns(
	idA: string,
	idB: string,
	datasourceId?: string
): ResultAsync<BuildComparison, ApiError> {
	const params = new URLSearchParams({ run_a: idA, run_b: idB });
	if (datasourceId) {
		params.set('datasource_id', datasourceId);
	}
	return apiRequest<BuildComparison>(`/v1/engine-runs/compare?${params.toString()}`);
}

export type EngineRunsSnapshotMessage = { type: 'snapshot'; runs: EngineRun[] };
export type EngineRunsErrorMessage = { type: 'error'; error: string; status_code?: number };
export type EngineRunsStreamMessage = EngineRunsSnapshotMessage | EngineRunsErrorMessage;

export interface EngineRunsStreamCallbacks {
	onSnapshot: (runs: EngineRun[]) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

function parseEngineRunsMessage(data: string): EngineRunsStreamMessage | null {
	try {
		return JSON.parse(data) as EngineRunsStreamMessage;
	} catch {
		return null;
	}
}

function buildEngineRunsEndpoint(params?: ListEngineRunsParams): string {
	const query = new URLSearchParams();
	if (params?.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params?.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params?.kind) query.set('kind', params.kind);
	if (params?.status) query.set('status', params.status);
	if (params?.limit !== undefined) query.set('limit', String(params.limit));
	if (params?.offset !== undefined) query.set('offset', String(params.offset));
	const suffix = query.toString() ? `?${query.toString()}` : '';
	return `/v1/engine-runs/ws${suffix}`;
}

export function connectEngineRunsStream(
	params: ListEngineRunsParams | undefined,
	callbacks: EngineRunsStreamCallbacks
): { close: () => void } {
	const url = buildWebsocketUrl(buildEngineRunsEndpoint(params));
	const socket = new WebSocket(url);

	socket.addEventListener('message', (event) => {
		const msg = parseEngineRunsMessage(event.data as string);
		if (!msg) return;
		if (msg.type === 'snapshot') {
			callbacks.onSnapshot(msg.runs);
			return;
		}
		if (msg.type === 'error') {
			callbacks.onError(msg.error);
		}
	});

	socket.addEventListener('error', () => {
		callbacks.onError('WebSocket connection failed');
	});

	socket.addEventListener('close', (event) => {
		if (event.code !== 1000 && event.code !== 1005) {
			callbacks.onError(event.reason || `Connection closed (code ${event.code})`);
		}
		callbacks.onClose();
	});

	return {
		close() {
			if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
				socket.close(1000);
			}
		}
	};
}
