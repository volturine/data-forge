import type {
	ComputeWorkerRun,
	ComputeWorkerRunExecutionEntry
} from '$lib/api/compute-worker-runs';
import type {
	BuildRunDetail,
	BuildLogEntry,
	BuildLogLevel,
	BuildQueryPlanSnapshot,
	BuildResourceConfigSummary,
	BuildResourceSnapshot,
	BuildStepSnapshot,
	BuildTabResult
} from '$lib/types/build-stream';
import {
	buildStepStateFromComputeWorkerRunStatus,
	buildStepTypeFromExecutionEntry,
	countComputeWorkerRunSteps,
	computeWorkerRunStatusToBuildLifecycleStatus,
	isPlanExecutionEntry,
	readBuildTabStatus,
	readComputeWorkerRunKind
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

function readLogLevel(value: unknown): BuildLogLevel | null {
	if (value === 'info' || value === 'warning' || value === 'error') return value;
	return null;
}

function readResourceSnapshot(value: unknown): BuildResourceSnapshot | null {
	const resource = readObject(value);
	if (!resource) return null;
	const sampledAt = readString(resource.sampled_at);
	const cpuPercent = readNumber(resource.cpu_percent);
	const memoryMb = readNumber(resource.memory_mb);
	const activeThreads = readNumber(resource.active_threads);
	if (sampledAt === null || cpuPercent === null || memoryMb === null || activeThreads === null) {
		return null;
	}
	return {
		sampled_at: sampledAt,
		cpu_percent: cpuPercent,
		memory_mb: memoryMb,
		memory_limit_mb: readNumber(resource.memory_limit_mb),
		active_threads: activeThreads,
		max_threads: readNumber(resource.max_threads)
	};
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

function readBuildResults(
	run: ComputeWorkerRun,
	result: Record<string, unknown> | null
): BuildTabResult[] {
	const results = readArray<Record<string, unknown>>(result?.results);
	return results.flatMap((item): BuildTabResult[] => {
		const tabId = readString(item.tab_id);
		const tabName = readString(item.tab_name);
		const status = readBuildTabStatus(item.status);
		if (tabId === null || tabName === null || status === null) return [];
		return [
			{
				tab_id: tabId,
				tab_name: tabName,
				status,
				output_id: readString(item.output_id),
				output_name: readString(item.output_name),
				error: readString(item.error)
			}
		];
	});
}

export function computeWorkerRunStatus(
	run: ComputeWorkerRun
): 'running' | 'completed' | 'failed' | 'cancelled' {
	return computeWorkerRunStatusToBuildLifecycleStatus(run.status);
}

export function computeWorkerRunOutputName(run: ComputeWorkerRun): string | null {
	const result = readObject(run.result_json);
	return readString(result?.current_output_name);
}

export function computeWorkerRunDatasourceId(run: ComputeWorkerRun): string {
	const result = readObject(run.result_json);
	const sourceId = readString(result?.source_datasource_id);
	if (sourceId !== null) return sourceId;
	return run.datasource_id;
}

export function computeWorkerRunDatasourceName(run: ComputeWorkerRun): string | null {
	const result = readObject(run.result_json);
	return readString(result?.source_datasource_name);
}

export function computeWorkerRunEstimatedRemainingMs(run: ComputeWorkerRun): number | null {
	const result = readObject(run.result_json);
	return readNumber(result?.estimated_remaining_ms);
}

export function computeWorkerRunCurrentStepIndex(run: ComputeWorkerRun): number | null {
	const result = readObject(run.result_json);
	return readNumber(result?.current_step_index);
}

export function computeWorkerRunTotalSteps(run: ComputeWorkerRun): number {
	const result = readObject(run.result_json);
	return readNumber(result?.total_steps) ?? countComputeWorkerRunSteps(run.execution_entries);
}

export function computeWorkerRunTotalTabs(run: ComputeWorkerRun): number {
	const result = readObject(run.result_json);
	return readNumber(result?.total_tabs) ?? 0;
}

export function computeWorkerRunResourceConfig(
	run: ComputeWorkerRun
): BuildResourceConfigSummary | null {
	const result = readObject(run.result_json);
	return readResourceConfig(result?.resource_config);
}

function stepsFromExecutionEntries(
	entries: ComputeWorkerRunExecutionEntry[],
	tabId: string | null,
	tabName: string | null,
	runStatus: ComputeWorkerRun['status']
): BuildStepSnapshot[] {
	const steps = entries
		.filter((entry) => !isPlanExecutionEntry(entry))
		.sort((a, b) => a.order - b.order);
	return steps.map((entry, index): BuildStepSnapshot => ({
		build_step_index: index,
		step_index: index,
		step_id: entry.key,
		step_name: entry.label,
		step_type: buildStepTypeFromExecutionEntry(entry),
		tab_id: tabId,
		tab_name: tabName,
		state: buildStepStateFromComputeWorkerRunStatus(runStatus, {
			isLastStep: index === steps.length - 1
		}),
		duration_ms: entry.duration_ms,
		row_count: null,
		error: null
	}));
}

function queryPlansFromExecutionEntries(
	entries: ComputeWorkerRunExecutionEntry[],
	tabId: string | null,
	tabName: string | null
): BuildQueryPlanSnapshot[] {
	return entries
		.filter((entry) => isPlanExecutionEntry(entry))
		.filter((e) => e.optimized_plan || e.unoptimized_plan)
		.map((entry): BuildQueryPlanSnapshot => ({
			tab_id: tabId,
			tab_name: tabName,
			optimized_plan: entry.optimized_plan ?? '',
			unoptimized_plan: entry.unoptimized_plan ?? ''
		}));
}

export function computeWorkerRunBuildDetail(run: ComputeWorkerRun): BuildRunDetail {
	const result = readObject(run.result_json);
	const tabId = readString(result?.current_tab_id);
	const tabName = readString(result?.current_tab_name);

	const steps = stepsFromExecutionEntries(run.execution_entries, tabId, tabName, run.status);
	const queryPlans = queryPlansFromExecutionEntries(run.execution_entries, tabId, tabName);

	const resources = readArray<Record<string, unknown>>(result?.resources)
		.map((resource) => readResourceSnapshot(resource))
		.filter((resource): resource is BuildResourceSnapshot => resource !== null);
	const latestResources =
		resources.at(-1) ?? readResourceSnapshot(result?.latest_resources) ?? null;
	const logs = readArray<Record<string, unknown>>(result?.logs).flatMap(
		(entry): BuildLogEntry[] => {
			const timestamp = readString(entry.timestamp);
			const level = readLogLevel(entry.level);
			const message = readString(entry.message);
			if (timestamp === null || level === null || message === null) return [];
			return [
				{
					timestamp,
					level,
					message,
					step_name: readString(entry.step_name),
					step_id: readString(entry.step_id),
					tab_id: readString(entry.tab_id),
					tab_name: readString(entry.tab_name)
				}
			];
		}
	);
	const results = readBuildResults(run, result);
	return {
		build_id: run.id,
		analysis_id: run.analysis_id ?? '',
		analysis_name: run.analysis_id ?? '',
		namespace: '',
		status: computeWorkerRunStatus(run),
		started_at: run.created_at,
		starter: {
			user_id: null,
			display_name: null,
			email: null,
			triggered_by: run.triggered_by
		},
		resource_config: computeWorkerRunResourceConfig(run),
		progress: run.progress,
		elapsed_ms: run.duration_ms ?? 0,
		estimated_remaining_ms: computeWorkerRunEstimatedRemainingMs(run),
		current_step: run.current_step,
		current_step_index: computeWorkerRunCurrentStepIndex(run),
		total_steps: computeWorkerRunTotalSteps(run),
		current_kind: readComputeWorkerRunKind(run.kind),
		current_datasource_id: computeWorkerRunDatasourceId(run),
		current_tab_id: readString(result?.current_tab_id),
		current_tab_name: readString(result?.current_tab_name),
		current_output_id: readString(result?.current_output_id),
		current_output_name: computeWorkerRunOutputName(run),
		current_compute_worker_run_id: run.id,
		total_tabs: computeWorkerRunTotalTabs(run),
		cancelled_at: readString(result?.cancelled_at),
		cancelled_by: readString(result?.cancelled_by),
		steps,
		query_plans: queryPlans,
		latest_resources: latestResources,
		resources,
		logs,
		results,
		duration_ms: run.duration_ms,
		error: run.error_message,
		request_json: run.request_json,
		result_json: run.result_json
	};
}
