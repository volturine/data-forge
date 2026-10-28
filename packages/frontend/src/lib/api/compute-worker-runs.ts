import { apiRequest } from './client';
import type { ApiError } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ComputeWorkerRunExecutionCategory } from '#lib/types/protocol-enum-tokens.js';
import { withQuery } from './query';

export interface ComputeWorkerRunExecutionEntry {
	key: string;
	label: string;
	category: ComputeWorkerRunExecutionCategory;
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
	return apiRequest<DurationStatsResponse>(
		withQuery('/v1/compute-worker-runs/stats', {
			analysis_id: params?.analysis_id,
			datasource_id: params?.datasource_id,
			kind: params?.kind,
			limit: params?.limit
		})
	);
}
