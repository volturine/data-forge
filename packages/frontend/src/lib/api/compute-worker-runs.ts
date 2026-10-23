import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';

export interface ComputeWorkerRunExecutionEntry {
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

export interface ComputeWorkerRun {
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
	execution_entries: ComputeWorkerRunExecutionEntry[];
}

export interface DurationStatsRun {
	id: string;
	started_at: string;
	duration_ms: number | null;
	status: string;
}

export interface DurationTrend {
	direction: 'decreasing' | 'stable' | 'increasing' | 'insufficient_data';
	change_pct: number | null;
	older_avg_ms: number | null;
	recent_avg_ms: number | null;
	older_count: number;
	recent_count: number;
	sample_size: number;
	threshold_pct: number;
	summary: string;
}

export interface DurationStatsResponse {
	runs: DurationStatsRun[];
	avg_duration_ms: number | null;
	p50_duration_ms: number | null;
	p95_duration_ms: number | null;
	trend: DurationTrend;
}

export interface DurationStatsParams {
	analysis_id?: string;
	datasource_id?: string;
	kind?: string;
	limit?: number;
}

export function getDurationStats(
	params?: DurationStatsParams
): ResultAsync<DurationStatsResponse, ApiError> {
	const query = new URLSearchParams();
	if (params?.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params?.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params?.kind) query.set('kind', params.kind);
	if (params?.limit !== undefined) query.set('limit', String(params.limit));
	const qs = query.toString();
	return apiRequest<DurationStatsResponse>(`/v1/compute-worker-runs/stats${qs ? `?${qs}` : ''}`);
}
