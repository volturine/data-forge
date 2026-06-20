import type {
	BuildEventContextJson,
	BuildEventJson,
	BuildTabResultJson
} from '$lib/protocol/dataforge_protocol/compute_pb';
import type {
	BuildLogLevelJson,
	BuildTabStatusJson,
	EngineRunKindJson
} from '$lib/protocol/dataforge_protocol/enums_pb';
import type { BuildEvent, BuildTabResult } from '$lib/types/build-stream';
import {
	BUILD_LOG_LEVEL_JSON_TOKENS,
	BUILD_TAB_STATUS_JSON_TOKENS,
	ENGINE_RUN_KIND_JSON_TOKENS
} from '$lib/types/protocol-enum-tokens';
import type { BuildLogLevel, BuildTabStatus, EngineRunKind } from '$lib/types/protocol-enum-tokens';

type BuildEventOneofKey =
	| 'cancelled'
	| 'completed'
	| 'failed'
	| 'log'
	| 'plan'
	| 'progress'
	| 'resources'
	| 'stepCompleted'
	| 'stepFailed'
	| 'stepStarted';

type BuildEventBase = Pick<
	BuildEvent,
	| 'analysis_id'
	| 'build_id'
	| 'current_datasource_id'
	| 'current_kind'
	| 'current_output_id'
	| 'current_output_name'
	| 'emitted_at'
	| 'engine_run_id'
	| 'sequence'
	| 'tab_id'
	| 'tab_name'
>;

const EVENT_KEYS: BuildEventOneofKey[] = [
	'cancelled',
	'completed',
	'failed',
	'log',
	'plan',
	'progress',
	'resources',
	'stepCompleted',
	'stepFailed',
	'stepStarted'
];

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function hasProtocolEventCase(value: Record<string, unknown>): boolean {
	return EVENT_KEYS.filter((key) => isObject(value[key])).length === 1;
}

export function isProtocolBuildEvent(value: unknown): value is BuildEventJson {
	if (!isObject(value)) return false;
	if (!isObject(value.context)) return false;
	return hasProtocolEventCase(value);
}

function requiredString(value: unknown): string | null {
	return typeof value === 'string' && value.length > 0 ? value : null;
}

function optionalString(value: unknown): string | null {
	return typeof value === 'string' ? value : null;
}

function requiredNumber(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function optionalNumber(value: unknown): number | null {
	if (value === undefined || value === null) return null;
	return requiredNumber(value);
}

function optionalInt64(value: unknown): number | null {
	if (value === undefined || value === null) return null;
	if (typeof value === 'number' && Number.isSafeInteger(value)) return value;
	if (typeof value === 'string') {
		const parsed = Number(value);
		return Number.isSafeInteger(parsed) ? parsed : null;
	}
	return null;
}

function engineRunKindToken(value: EngineRunKindJson | undefined): EngineRunKind | null {
	return value === undefined ? null : (ENGINE_RUN_KIND_JSON_TOKENS[value] ?? null);
}

function buildTabStatusToken(value: BuildTabStatusJson | undefined): BuildTabStatus | null {
	return value === undefined ? null : (BUILD_TAB_STATUS_JSON_TOKENS[value] ?? null);
}

function buildLogLevelToken(value: BuildLogLevelJson | undefined): BuildLogLevel | null {
	return value === undefined ? null : (BUILD_LOG_LEVEL_JSON_TOKENS[value] ?? null);
}

function baseFromContext(context: BuildEventContextJson | undefined): BuildEventBase | null {
	if (context === undefined) return null;
	const buildId = requiredString(context.buildId);
	const analysisId = requiredString(context.analysisId);
	const emittedAt = requiredString(context.emittedAt);
	if (buildId === null || analysisId === null || emittedAt === null) return null;
	return {
		build_id: buildId,
		analysis_id: analysisId,
		emitted_at: emittedAt,
		sequence: context.sequence ?? null,
		current_kind: engineRunKindToken(context.currentKind),
		current_datasource_id: context.currentDatasourceId ?? null,
		tab_id: context.tabId ?? null,
		tab_name: context.tabName ?? null,
		current_output_id: context.currentOutputId ?? null,
		current_output_name: context.currentOutputName ?? null,
		engine_run_id: context.engineRunId ?? null
	};
}

function tabResultFromProtocol(result: BuildTabResultJson): BuildTabResult | null {
	const tabId = requiredString(result.tabId);
	const status = buildTabStatusToken(result.status);
	if (tabId === null || status === null) return null;
	return {
		tab_id: tabId,
		tab_name: result.tabName ?? '',
		status,
		output_id: result.outputId ?? null,
		output_name: result.outputName ?? null,
		error: result.error ?? null
	};
}

function tabResultsFromProtocol(
	results: BuildTabResultJson[] | undefined
): BuildTabResult[] | null {
	const converted = (results ?? []).map(tabResultFromProtocol);
	return converted.every((result): result is BuildTabResult => result !== null) ? converted : null;
}

export function protocolBuildEventToBuildEvent(event: BuildEventJson): BuildEvent | null {
	const base = baseFromContext(event.context);
	if (base === null) return null;

	if (event.plan !== undefined) {
		return {
			...base,
			type: 'plan',
			optimized_plan: event.plan.optimizedPlan ?? '',
			unoptimized_plan: event.plan.unoptimizedPlan ?? ''
		};
	}

	if (event.stepStarted !== undefined) {
		const buildStepIndex = requiredNumber(event.stepStarted.buildStepIndex);
		const stepIndex = requiredNumber(event.stepStarted.stepIndex);
		const stepId = requiredString(event.stepStarted.stepId);
		if (buildStepIndex === null || stepIndex === null || stepId === null) return null;
		return {
			...base,
			type: 'step_start',
			build_step_index: buildStepIndex,
			step_index: stepIndex,
			step_id: stepId,
			step_name: event.stepStarted.stepName ?? '',
			step_type: event.stepStarted.stepType ?? '',
			total_steps: event.stepStarted.totalSteps ?? 0
		};
	}

	if (event.stepCompleted !== undefined) {
		const buildStepIndex = requiredNumber(event.stepCompleted.buildStepIndex);
		const stepIndex = requiredNumber(event.stepCompleted.stepIndex);
		const stepId = requiredString(event.stepCompleted.stepId);
		const durationMs = requiredNumber(event.stepCompleted.durationMs);
		if (buildStepIndex === null || stepIndex === null || stepId === null || durationMs === null)
			return null;
		return {
			...base,
			type: 'step_complete',
			build_step_index: buildStepIndex,
			step_index: stepIndex,
			step_id: stepId,
			step_name: event.stepCompleted.stepName ?? '',
			step_type: event.stepCompleted.stepType ?? '',
			duration_ms: durationMs,
			row_count: optionalInt64(event.stepCompleted.rowCount),
			total_steps: event.stepCompleted.totalSteps ?? 0
		};
	}

	if (event.stepFailed !== undefined) {
		const buildStepIndex = requiredNumber(event.stepFailed.buildStepIndex);
		const stepIndex = requiredNumber(event.stepFailed.stepIndex);
		const stepId = requiredString(event.stepFailed.stepId);
		const error = requiredString(event.stepFailed.error);
		if (buildStepIndex === null || stepIndex === null || stepId === null || error === null)
			return null;
		return {
			...base,
			type: 'step_failed',
			build_step_index: buildStepIndex,
			step_index: stepIndex,
			step_id: stepId,
			step_name: event.stepFailed.stepName ?? '',
			step_type: event.stepFailed.stepType ?? '',
			error,
			total_steps: event.stepFailed.totalSteps ?? 0
		};
	}

	if (event.progress !== undefined) {
		const progress = requiredNumber(event.progress.progress);
		const elapsedMs = requiredNumber(event.progress.elapsedMs);
		if (progress === null || elapsedMs === null) return null;
		return {
			...base,
			type: 'progress',
			progress,
			elapsed_ms: elapsedMs,
			estimated_remaining_ms: optionalNumber(event.progress.estimatedRemainingMs),
			current_step: optionalString(event.progress.currentStep),
			current_step_index: optionalNumber(event.progress.currentStepIndex),
			total_steps: event.progress.totalSteps ?? 0
		};
	}

	if (event.resources !== undefined) {
		const cpuPercent = requiredNumber(event.resources.cpuPercent);
		const memoryMb = requiredNumber(event.resources.memoryMb);
		const activeThreads = requiredNumber(event.resources.activeThreads);
		if (cpuPercent === null || memoryMb === null || activeThreads === null) return null;
		return {
			...base,
			type: 'resources',
			cpu_percent: cpuPercent,
			memory_mb: memoryMb,
			memory_limit_mb: optionalNumber(event.resources.memoryLimitMb),
			active_threads: activeThreads,
			max_threads: optionalNumber(event.resources.maxThreads)
		};
	}

	if (event.log !== undefined) {
		const level = buildLogLevelToken(event.log.level);
		const message = requiredString(event.log.message);
		if (level === null || message === null) return null;
		return {
			...base,
			type: 'log',
			level,
			message,
			step_name: event.log.stepName ?? null,
			step_id: event.log.stepId ?? null
		};
	}

	const terminal = event.completed ?? event.failed ?? event.cancelled;
	if (terminal === undefined) return null;
	const progress = requiredNumber(terminal.progress);
	const elapsedMs = requiredNumber(terminal.elapsedMs);
	const durationMs = requiredNumber(terminal.durationMs);
	const results = tabResultsFromProtocol(terminal.results);
	if (progress === null || elapsedMs === null || durationMs === null || results === null)
		return null;
	const payload = {
		...base,
		progress,
		elapsed_ms: elapsedMs,
		total_steps: terminal.totalSteps ?? 0,
		tabs_built: terminal.tabsBuilt ?? 0,
		results,
		duration_ms: durationMs
	};
	if (event.completed !== undefined) return { ...payload, type: 'complete' };
	if (event.failed !== undefined)
		return { ...payload, type: 'failed', error: terminal.error ?? null };
	return {
		...payload,
		type: 'cancelled',
		cancelled_at: terminal.cancelledAt ?? base.emitted_at,
		cancelled_by: terminal.cancelledBy ?? null
	};
}
