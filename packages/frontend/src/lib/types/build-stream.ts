import type {
	EngineRun,
	EngineRunExecutionEntry,
	ListEngineRunsParams
} from '$lib/api/engine-runs';
import type {
	ActiveBuildStatus,
	BuildLogLevel,
	BuildStepState,
	BuildTabStatus,
	EngineRunKind
} from '$lib/types/protocol-enum-tokens';

export type { ActiveBuildStatus, BuildLogLevel, BuildStepState, BuildTabStatus, EngineRunKind };

export interface BuildPlanEvent {
	type: 'plan';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	optimized_plan: string;
	unoptimized_plan: string;
}

export interface BuildStepStartEvent {
	type: 'step_start';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	total_steps: number;
}

export interface BuildStepCompleteEvent {
	type: 'step_complete';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	duration_ms: number;
	row_count: number | null;
	total_steps: number;
}

export interface BuildStepFailedEvent {
	type: 'step_failed';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	error: string;
	total_steps: number;
}

export interface BuildProgressEvent {
	type: 'progress';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	progress: number;
	elapsed_ms: number;
	estimated_remaining_ms: number | null;
	current_step: string | null;
	current_step_index: number | null;
	total_steps: number;
}

export interface BuildResourceEvent {
	type: 'resources';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	cpu_percent: number;
	memory_mb: number;
	memory_limit_mb: number | null;
	active_threads: number;
	max_threads: number | null;
}

export interface BuildLogEvent {
	type: 'log';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	level: BuildLogLevel;
	message: string;
	step_name: string | null;
	step_id: string | null;
}

export interface BuildTabResult {
	tab_id: string;
	tab_name: string;
	status: BuildTabStatus;
	output_id: string | null;
	output_name: string | null;
	error: string | null;
}

export interface BuildCompleteEvent {
	type: 'complete';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	progress: number;
	elapsed_ms: number;
	total_steps: number;
	tabs_built: number;
	results: BuildTabResult[];
	duration_ms: number;
}

export interface BuildFailedEvent {
	type: 'failed';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	progress: number;
	elapsed_ms: number;
	total_steps: number;
	tabs_built: number;
	results: BuildTabResult[];
	duration_ms: number;
	error: string | null;
}

export interface BuildCancelledEvent {
	type: 'cancelled';
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	sequence: number | null;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	engine_run_id: string | null;
	progress: number;
	elapsed_ms: number;
	total_steps: number;
	tabs_built: number;
	results: BuildTabResult[];
	duration_ms: number;
	cancelled_at: string;
	cancelled_by: string | null;
}

export type BuildEvent =
	| BuildCancelledEvent
	| BuildCompleteEvent
	| BuildFailedEvent
	| BuildLogEvent
	| BuildPlanEvent
	| BuildProgressEvent
	| BuildResourceEvent
	| BuildStepCompleteEvent
	| BuildStepFailedEvent
	| BuildStepStartEvent;

export interface BuildStarter {
	user_id: string | null;
	display_name: string | null;
	email: string | null;
	triggered_by: string | null;
}

export interface BuildResourceConfigSummary {
	max_threads: number | null;
	max_memory_mb: number | null;
	streaming_chunk_size: number | null;
}

export interface ActiveBuildSummary {
	build_id: string;
	analysis_id: string;
	analysis_name: string;
	namespace: string;
	status: ActiveBuildStatus;
	started_at: string;
	starter: BuildStarter;
	resource_config: BuildResourceConfigSummary | null;
	progress: number;
	elapsed_ms: number;
	estimated_remaining_ms: number | null;
	current_step: string | null;
	current_step_index: number | null;
	total_steps: number;
	current_kind: EngineRunKind | null;
	current_datasource_id: string | null;
	current_tab_id: string | null;
	current_tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	current_engine_run_id: string | null;
	total_tabs: number;
	cancelled_at: string | null;
	cancelled_by: string | null;
	result_json: Record<string, unknown> | null;
}

export interface BuildStepSnapshot {
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	tab_id: string | null;
	tab_name: string | null;
	state: BuildStepState;
	duration_ms: number | null;
	row_count: number | null;
	error: string | null;
}

export interface BuildQueryPlanSnapshot {
	tab_id: string | null;
	tab_name: string | null;
	optimized_plan: string;
	unoptimized_plan: string;
}

export interface BuildResourceSnapshot {
	sampled_at: string;
	cpu_percent: number;
	memory_mb: number;
	memory_limit_mb: number | null;
	active_threads: number;
	max_threads: number | null;
}

export interface BuildLogEntry {
	timestamp: string;
	level: BuildLogLevel;
	message: string;
	step_name: string | null;
	step_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
}

export interface ActiveBuildDetail extends ActiveBuildSummary {
	steps: BuildStepSnapshot[];
	query_plans: BuildQueryPlanSnapshot[];
	latest_resources: BuildResourceSnapshot | null;
	resources: BuildResourceSnapshot[];
	logs: BuildLogEntry[];
	results: BuildTabResult[];
	duration_ms: number | null;
	error: string | null;
	request_json: Record<string, unknown> | null;
}

export interface BuildDetailSnapshot {
	type: 'snapshot';
	build: ActiveBuildDetail;
	last_sequence?: number;
}

export interface BuildsSnapshot {
	type: 'snapshot';
	builds: ActiveBuildSummary[];
}

export interface BuildWebsocketErrorMessage {
	type: 'error';
	error: string;
	status_code: number;
}

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

const ENGINE_RUN_KINDS = new Set<EngineRunKind>([
	'build',
	'preview',
	'row_count',
	'download',
	'ingest'
]);
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
	download: 'Download',
	ingest: 'Ingest'
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

export function engineRunDisplayKind(kind: EngineRunKind | string): EngineRunKind | string {
	if (kind === 'raw') return 'build';
	const parsed = readEngineRunKind(kind);
	if (parsed === 'ingest') return 'build';
	return parsed ?? kind;
}

export function engineRunKindLabel(kind: EngineRunKind | string): string {
	const parsed = readEngineRunKind(engineRunDisplayKind(kind));
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
