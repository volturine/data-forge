import type {
	EngineRun,
	EngineRunExecutionEntry,
	ListEngineRunsParams
} from '$lib/api/engine-runs';
import type {
	ActiveBuildStatus,
	BuildLogEntry,
	BuildResourceConfigSummary,
	BuildResourceSnapshot,
	BuildStepState,
	BuildTabResult,
	EngineRunKind
} from './build-stream.generated';

export type {
	ActiveBuildDetail,
	ActiveBuildSummary,
	BuildDetailSnapshot,
	BuildsSnapshot,
	BuildEvent,
	BuildLogLevel,
	EngineRunKind,
	BuildQueryPlanSnapshot,
	BuildStepSnapshot,
	BuildTabStatus,
	BuildWebsocketErrorMessage
} from './build-stream.generated';

export type BuildStatus =
	| 'connecting'
	| 'queued'
	| 'running'
	| 'completed'
	| 'failed'
	| 'cancelled'
	| 'disconnected';

export type BuildStatusTone = 'accent' | 'success' | 'warning' | 'error';
export type ActiveBuildStatusTone = 'success' | 'active' | 'warning' | 'error';
export type MonitoringStatusFilter = 'all' | 'running' | 'completed' | 'failed' | 'cancelled';

export type StepInfo = {
	buildStepIndex: number;
	stepIndex: number;
	stepId: string;
	name: string;
	stepType: string;
	tabId: string | null;
	tabName: string | null;
	state: BuildStepState;
	duration: number | null;
	rowCount: number | null;
	error: string | null;
};

export type QueryPlan = {
	tabId: string | null;
	tabName: string | null;
	optimized: string;
	unoptimized: string;
};

export type {
	BuildLogEntry,
	BuildResourceConfigSummary,
	BuildResourceSnapshot,
	BuildStepState,
	BuildTabResult
};

const ENGINE_RUN_KINDS = new Set<EngineRunKind>(['build', 'preview', 'row_count', 'download']);
const BUILD_STEP_STATES = new Set<BuildStepState>([
	'pending',
	'running',
	'completed',
	'failed',
	'skipped'
]);
const ACTIVE_BUILD_STATUSES = new Set<ActiveBuildStatus>([
	'queued',
	'running',
	'completed',
	'failed',
	'cancelled'
]);
const BUILD_TAB_STATUSES = new Set<BuildTabResult['status']>(['success', 'failed']);
const BUILD_STATUS_TONES: Record<BuildStatus, BuildStatusTone> = {
	connecting: 'accent',
	queued: 'accent',
	running: 'accent',
	completed: 'success',
	failed: 'error',
	cancelled: 'warning',
	disconnected: 'error'
};
const ACTIVE_BUILD_STATUS_LABELS: Record<ActiveBuildStatus, string> = {
	queued: 'Queued',
	running: 'Running',
	completed: 'Success',
	failed: 'Failed',
	cancelled: 'Cancelled'
};
const ACTIVE_BUILD_STATUS_TONES: Record<ActiveBuildStatus, ActiveBuildStatusTone> = {
	queued: 'active',
	running: 'active',
	completed: 'success',
	failed: 'error',
	cancelled: 'warning'
};
const ENGINE_RUN_KIND_LABELS: Record<EngineRunKind, string> = {
	build: 'Build',
	preview: 'Preview',
	row_count: 'Row Count',
	download: 'Download'
};
const BUILD_TAB_STATUS_LABELS: Record<BuildTabResult['status'], string> = {
	success: 'Success',
	failed: 'Failed'
};
const BUILD_TAB_STATUS_TONES: Record<BuildTabResult['status'], 'success' | 'error'> = {
	success: 'success',
	failed: 'error'
};

export function readEngineRunKind(value: unknown): EngineRunKind | null {
	return typeof value === 'string' && ENGINE_RUN_KINDS.has(value as EngineRunKind)
		? (value as EngineRunKind)
		: null;
}

export function readBuildStepState(value: unknown): BuildStepState | null {
	return typeof value === 'string' && BUILD_STEP_STATES.has(value as BuildStepState)
		? (value as BuildStepState)
		: null;
}

export function coerceBuildStepState(value: unknown): BuildStepState {
	return readBuildStepState(value) ?? 'pending';
}

export function readActiveBuildStatus(value: unknown): ActiveBuildStatus | null {
	return typeof value === 'string' && ACTIVE_BUILD_STATUSES.has(value as ActiveBuildStatus)
		? (value as ActiveBuildStatus)
		: null;
}

export function isTerminalBuildStatus(status: BuildStatus): boolean {
	return status === 'completed' || status === 'failed' || status === 'cancelled';
}

export function buildStatusFromActiveBuild(status: ActiveBuildStatus): BuildStatus {
	return status;
}

export function buildStatusLabel(status: BuildStatus, currentStep: string | null = null): string {
	switch (status) {
		case 'connecting':
			return 'Connecting';
		case 'running':
			return currentStep ?? 'Running';
		case 'completed':
			return 'Complete';
		case 'failed':
			return 'Failed';
		case 'cancelled':
			return 'Cancelled';
		case 'queued':
			return 'Queued';
		case 'disconnected':
			return 'Disconnected';
	}
}

export function buildStatusTone(status: BuildStatus): BuildStatusTone {
	return BUILD_STATUS_TONES[status];
}

export function activeBuildStatusLabel(status: ActiveBuildStatus): string {
	return ACTIVE_BUILD_STATUS_LABELS[status];
}

export function activeBuildStatusTone(status: ActiveBuildStatus): ActiveBuildStatusTone {
	return ACTIVE_BUILD_STATUS_TONES[status];
}

export function isTerminalActiveBuildStatus(status: ActiveBuildStatus): boolean {
	return status === 'completed' || status === 'failed' || status === 'cancelled';
}

export function canCancelActiveBuildStatus(status: ActiveBuildStatus): boolean {
	return status === 'queued' || status === 'running';
}

export function engineRunStatusToActiveBuildStatus(
	status: EngineRun['status']
): Exclude<ActiveBuildStatus, 'queued'> {
	return status === 'success' ? 'completed' : status;
}

export function engineRunStatusFilterValue(
	status: MonitoringStatusFilter
): ListEngineRunsParams['status'] {
	if (status === 'all') return undefined;
	return status === 'completed' ? 'success' : status;
}

export function engineRunKindLabel(kind: EngineRunKind | string): string {
	const parsed = readEngineRunKind(kind);
	return parsed === null ? kind : ENGINE_RUN_KIND_LABELS[parsed];
}

export function readBuildTabStatus(value: unknown): BuildTabResult['status'] | null {
	return typeof value === 'string' && BUILD_TAB_STATUSES.has(value as BuildTabResult['status'])
		? (value as BuildTabResult['status'])
		: null;
}

export function buildTabStatusLabel(status: BuildTabResult['status']): string {
	return BUILD_TAB_STATUS_LABELS[status];
}

export function buildTabStatusTone(status: BuildTabResult['status']): 'success' | 'error' {
	return BUILD_TAB_STATUS_TONES[status];
}

export function isPlanExecutionEntry(entry: Pick<EngineRunExecutionEntry, 'category'>): boolean {
	return entry.category === 'plan';
}

export function buildStepTypeFromExecutionEntry(
	entry: Pick<EngineRunExecutionEntry, 'category' | 'metadata'>
): string {
	const stepType = entry.metadata?.step_type;
	if (typeof stepType === 'string' && stepType.length > 0) return stepType;
	switch (entry.category) {
		case 'read':
		case 'write':
			return entry.category;
		default:
			return 'unknown';
	}
}

export function buildStepStateFromEngineRunStatus(
	status: EngineRun['status'],
	options: { isLastStep: boolean }
): BuildStepState {
	return status === 'failed' && options.isLastStep ? 'failed' : 'completed';
}

export function countEngineRunSteps(entries: EngineRunExecutionEntry[]): number {
	return entries.filter((entry) => !isPlanExecutionEntry(entry)).length;
}
