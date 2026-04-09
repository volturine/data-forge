import type { EngineRun } from '$lib/api/engine-runs';
import type {
	ActiveBuildDetail,
	BuildLogEntry,
	BuildQueryPlanSnapshotWire,
	BuildResourceConfigSummary,
	BuildResourceSnapshot,
	BuildStepSnapshotWire,
	BuildTabResult
} from '$lib/types/build-stream';

function readArray<T>(value: unknown): T[] {
	return Array.isArray(value) ? (value as T[]) : [];
}

function readObject(value: unknown): Record<string, unknown> | null {
	return typeof value === 'object' && value !== null && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function readString(value: unknown): string | null {
	return typeof value === 'string' && value.length > 0 ? value : null;
}

function readNumber(value: unknown): number | null {
	return typeof value === 'number' ? value : null;
}

function readResourceConfig(value: unknown): BuildResourceConfigSummary | null {
	const config = readObject(value);
	if (!config) return null;
	return {
		max_threads: readNumber(config.max_threads),
		max_memory_mb: readNumber(config.max_memory_mb),
		streaming_chunk_size: readNumber(config.streaming_chunk_size)
	};
}

function readQueryPlans(result: Record<string, unknown> | null): BuildQueryPlanSnapshotWire[] {
	const plans = readArray<Record<string, unknown>>(result?.query_plans);
	return plans.map(
		(plan): BuildQueryPlanSnapshotWire => ({
			tab_id: readString(plan.tab_id),
			tab_name: readString(plan.tab_name),
			optimized_plan: readString(plan.optimized_plan) ?? '',
			unoptimized_plan: readString(plan.unoptimized_plan) ?? ''
		})
	);
}

function readBuildResults(
	run: EngineRun,
	result: Record<string, unknown> | null
): BuildTabResult[] {
	const results = readArray<Record<string, unknown>>(result?.results);
	if (results.length > 0) {
		return results.map(
			(item): BuildTabResult => ({
				tab_id: readString(item.tab_id) ?? run.id,
				tab_name: readString(item.tab_name) ?? engineRunOutputName(run) ?? 'Build',
				status: readString(item.status) === 'failed' ? 'failed' : 'success',
				output_id: readString(item.output_id),
				output_name: readString(item.output_name),
				error: readString(item.error)
			})
		);
	}
	return [];
}

export function engineRunStatus(run: EngineRun): 'running' | 'completed' | 'failed' {
	if (run.status === 'running') return 'running';
	return run.status === 'success' ? 'completed' : 'failed';
}

export function engineRunOutputName(run: EngineRun): string | null {
	const result = readObject(run.result_json);
	return readString(result?.current_output_name) ?? readString(result?.datasource_name);
}

export function engineRunDatasourceId(run: EngineRun): string {
	const result = readObject(run.result_json);
	return (
		readString(result?.source_datasource_id) ??
		readString(readObject(run.request_json)?.datasource_id) ??
		run.datasource_id
	);
}

export function engineRunDatasourceName(run: EngineRun): string | null {
	const result = readObject(run.result_json);
	return readString(result?.source_datasource_name);
}

export function engineRunCurrentTabName(run: EngineRun): string | null {
	const result = readObject(run.result_json);
	return readString(result?.current_tab_name);
}

export function engineRunEstimatedRemainingMs(run: EngineRun): number | null {
	const result = readObject(run.result_json);
	return readNumber(result?.estimated_remaining_ms);
}

export function engineRunCurrentStepIndex(run: EngineRun): number | null {
	const result = readObject(run.result_json);
	return readNumber(result?.current_step_index);
}

export function engineRunTotalSteps(run: EngineRun): number {
	const result = readObject(run.result_json);
	return readNumber(result?.total_steps) ?? 0;
}

export function engineRunTotalTabs(run: EngineRun): number {
	const result = readObject(run.result_json);
	return readNumber(result?.total_tabs) ?? 0;
}

export function engineRunResourceConfig(run: EngineRun): BuildResourceConfigSummary | null {
	const result = readObject(run.result_json);
	return readResourceConfig(result?.resource_config);
}

export function engineRunBuildDetail(run: EngineRun): ActiveBuildDetail {
	const result = readObject(run.result_json);
	const steps = readArray<Record<string, unknown>>(result?.steps).map(
		(step): BuildStepSnapshotWire => ({
			build_step_index: readNumber(step.build_step_index) ?? 0,
			step_index: readNumber(step.step_index) ?? 0,
			step_id: readString(step.step_id) ?? 'unknown',
			step_name: readString(step.step_name) ?? 'Unnamed step',
			step_type: readString(step.step_type) ?? 'unknown',
			tab_id: readString(step.tab_id),
			tab_name: readString(step.tab_name),
			state: readString(step.state) ?? 'pending',
			duration_ms: readNumber(step.duration_ms),
			row_count: readNumber(step.row_count),
			error: readString(step.error)
		})
	);
	const queryPlans = readQueryPlans(result);
	const resources = readArray<Record<string, unknown>>(result?.resources).map(
		(resource): BuildResourceSnapshot => ({
			sampled_at: readString(resource.sampled_at) ?? run.created_at,
			cpu_percent: readNumber(resource.cpu_percent) ?? 0,
			memory_mb: readNumber(resource.memory_mb) ?? 0,
			memory_limit_mb: readNumber(resource.memory_limit_mb),
			active_threads: readNumber(resource.active_threads) ?? 0,
			max_threads: readNumber(resource.max_threads)
		})
	);
	const latestResources = resources.at(-1) ?? null;
	const logs = readArray<Record<string, unknown>>(result?.logs).map(
		(entry): BuildLogEntry => ({
			timestamp: readString(entry.timestamp) ?? run.created_at,
			level: readString(entry.level) ?? 'info',
			message: readString(entry.message) ?? '',
			step_name: readString(entry.step_name),
			step_id: readString(entry.step_id),
			tab_id: readString(entry.tab_id),
			tab_name: readString(entry.tab_name)
		})
	);
	const results = readBuildResults(run, result);
	return {
		build_id: run.id,
		analysis_id: run.analysis_id ?? '',
		analysis_name: run.analysis_id ?? 'Build',
		namespace: '',
		status: engineRunStatus(run),
		started_at: run.created_at,
		starter: {
			user_id: null,
			display_name: null,
			email: null,
			triggered_by: run.triggered_by
		},
		resource_config: engineRunResourceConfig(run),
		progress: run.progress,
		elapsed_ms: run.duration_ms ?? 0,
		estimated_remaining_ms: engineRunEstimatedRemainingMs(run),
		current_step: run.current_step,
		current_step_index: engineRunCurrentStepIndex(run),
		total_steps: engineRunTotalSteps(run),
		current_tab_id: readString(result?.current_tab_id),
		current_tab_name: readString(result?.current_tab_name),
		current_output_id: readString(result?.current_output_id),
		current_output_name: engineRunOutputName(run),
		total_tabs: engineRunTotalTabs(run),
		steps,
		query_plans: queryPlans,
		latest_resources: latestResources,
		resources,
		logs,
		results,
		duration_ms: run.duration_ms,
		error: run.error_message
	};
}
