import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export interface EngineRun {
	id: string;
	analysis_id: string | null;
	datasource_id: string;
	kind: string;
	status: 'success' | 'failed';
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
	status?: 'success' | 'failed';
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
