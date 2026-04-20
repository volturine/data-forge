import type { EngineRun, EngineRunExecutionEntry } from '$lib/api/engine-runs';
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
	run: EngineRun,
	result: Record<string, unknown> | null
): BuildTabResult[] {
	const results = readArray<Record<string, unknown>>(result?.results);
	return results.flatMap((item): BuildTabResult[] => {
		const tabId = readString(item.tab_id);
		const tabName = readString(item.tab_name);
		const status = readString(item.status);
		if (tabId === null || tabName === null) return [];
		if (status !== 'success' && status !== 'failed') return [];
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

export function engineRunStatus(run: EngineRun): 'running' | 'completed' | 'failed' | 'cancelled' {
	if (run.status === 'running') return 'running';
	if (run.status === 'cancelled') return 'cancelled';
	return run.status === 'success' ? 'completed' : 'failed';
}

export function engineRunOutputName(run: EngineRun): string | null {
	const result = readObject(run.result_json);
	return readString(result?.current_output_name);
}

export function engineRunDatasourceId(run: EngineRun): string {
	const result = readObject(run.result_json);
	const sourceId = readString(result?.source_datasource_id);
	if (sourceId !== null) return sourceId;
	return run.datasource_id;
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
	return (
		readNumber(result?.total_steps) ??
		run.execution_entries.filter((entry) => entry.category !== 'plan').length
	);
}

export function engineRunTotalTabs(run: EngineRun): number {
	const result = readObject(run.result_json);
	return readNumber(result?.total_tabs) ?? 0;
}

export function engineRunResourceConfig(run: EngineRun): BuildResourceConfigSummary | null {
	const result = readObject(run.result_json);
	return readResourceConfig(result?.resource_config);
}

function stepsFromExecutionEntries(
	entries: EngineRunExecutionEntry[],
	tabId: string | null,
	tabName: string | null,
	runStatus: string
): BuildStepSnapshotWire[] {
	const nonPlan = entries.filter((e) => e.category !== 'plan').sort((a, b) => a.order - b.order);
	return nonPlan.map(
		(entry, index): BuildStepSnapshotWire => ({
			build_step_index: index,
			step_index: index,
			step_id: entry.key,
			step_name: entry.label,
			step_type: entry.category,
			tab_id: tabId,
			tab_name: tabName,
			state: runStatus === 'failed' && index === nonPlan.length - 1 ? 'failed' : 'completed',
			duration_ms: entry.duration_ms,
			row_count: null,
			error: null
		})
	);
}

function queryPlansFromExecutionEntries(
	entries: EngineRunExecutionEntry[],
	tabId: string | null,
	tabName: string | null
): BuildQueryPlanSnapshotWire[] {
	return entries
		.filter((e) => e.category === 'plan')
		.filter((e) => e.optimized_plan || e.unoptimized_plan)
		.map(
			(entry): BuildQueryPlanSnapshotWire => ({
				tab_id: tabId,
				tab_name: tabName,
				optimized_plan: entry.optimized_plan ?? '',
				unoptimized_plan: entry.unoptimized_plan ?? ''
			})
		);
}

export function engineRunBuildDetail(run: EngineRun): ActiveBuildDetail {
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
			const level = readString(entry.level);
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
		analysis_id: run.analysis_id ?? run.id,
		analysis_name: run.analysis_id ?? run.id,
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
		current_kind: run.kind,
		current_datasource_id: engineRunDatasourceId(run),
		current_tab_id: readString(result?.current_tab_id),
		current_tab_name: readString(result?.current_tab_name),
		current_output_id: readString(result?.current_output_id),
		current_output_name: engineRunOutputName(run),
		current_engine_run_id: run.id,
		total_tabs: engineRunTotalTabs(run),
		cancelled_at: readString(result?.cancelled_at),
		cancelled_by: readString(result?.cancelled_by),
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
