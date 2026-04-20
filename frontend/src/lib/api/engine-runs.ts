import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';

export interface EngineRunExecutionEntry {
	key: string;
	label: string;
	category: 'read' | 'step' | 'plan' | 'compute' | 'write';
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
	status: 'running' | 'success' | 'failed' | 'cancelled';
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

export interface ListEngineRunsParams {
	analysis_id?: string;
	datasource_id?: string;
	kind?: string;
	status?: 'running' | 'success' | 'failed' | 'cancelled';
	limit?: number;
	offset?: number;
}

function buildQueryString(params?: ListEngineRunsParams): string {
	if (!params) return '';
	const query = new URLSearchParams();
	if (params.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params.kind) query.set('kind', params.kind);
	if (params.status) query.set('status', params.status);
	if (params.limit !== undefined) query.set('limit', String(params.limit));
	if (params.offset !== undefined) query.set('offset', String(params.offset));
	const str = query.toString();
	return str ? `?${str}` : '';
}

export function listEngineRuns(
	params?: ListEngineRunsParams,
	signal?: AbortSignal
): ResultAsync<EngineRun[], ApiError> {
	return apiRequest<EngineRun[]>(`/v1/engine-runs${buildQueryString(params)}`, { signal });
}

export function getEngineRun(id: string): ResultAsync<EngineRun, ApiError> {
	return apiRequest<EngineRun>(`/v1/engine-runs/${id}`);
}
