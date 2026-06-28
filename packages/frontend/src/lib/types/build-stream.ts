import type {
	EngineRun,
	EngineRunExecutionEntry,
	ListEngineRunsParams
} from '$lib/api/engine-runs';
import type {
	ActiveBuildDetailJson as ProtocolActiveBuildDetailJson,
	ActiveBuildListResponseJson as ProtocolActiveBuildListResponseJson,
	ActiveBuildSummaryJson as ProtocolActiveBuildSummaryJson,
	BuildListSnapshotMessageJson as ProtocolBuildListSnapshotMessageJson,
	BuildLogEntryJson as ProtocolBuildLogEntryJson,
	BuildQueryPlanSnapshotJson as ProtocolBuildQueryPlanSnapshotJson,
	BuildResourceConfigSummaryJson as ProtocolBuildResourceConfigSummaryJson,
	BuildResourceSnapshotJson as ProtocolBuildResourceSnapshotJson,
	BuildSnapshotMessageJson as ProtocolBuildSnapshotMessageJson,
	BuildStarterJson as ProtocolBuildStarterJson,
	BuildStepKindJson as ProtocolBuildStepKindJson,
	BuildStepSnapshotJson as ProtocolBuildStepSnapshotJson,
	BuildTabResultJson as ProtocolBuildTabResultJson,
	BuildWebsocketErrorMessageJson as ProtocolBuildWebsocketErrorMessageJson
} from '$lib/protocol/dataforge_protocol/compute_pb';
import type {
	ActiveBuildStatus,
	BuildLogLevel,
	BuildStepState,
	BuildTabStatus,
	EngineRunKind
} from '$lib/types/protocol-enum-tokens';

export type { ActiveBuildStatus, BuildLogLevel, BuildStepState, BuildTabStatus, EngineRunKind };

type Field<T, K extends keyof T> = NonNullable<T[K]>;
type StringField<T, K extends keyof T> = Extract<Field<T, K>, string>;
type NumberField<T, K extends keyof T> = Extract<Field<T, K>, number>;
type OptionalStringField<T, K extends keyof T> = StringField<T, K> | null;
type OptionalNumberField<T, K extends keyof T> = NumberField<T, K> | null;
type StructHttpField<T, K extends keyof T> =
	Field<T, K> extends Record<string, unknown> ? Record<string, unknown> : never;
type OptionalStructHttpField<T, K extends keyof T> = StructHttpField<T, K> | null;
type Int64HttpNumber<T, K extends keyof T> = Field<T, K> extends string ? number : never;
type OptionalInt64HttpNumber<T, K extends keyof T> = Int64HttpNumber<T, K> | null;
type BuildStepTypeField =
	Field<ProtocolBuildStepSnapshotJson, 'stepKind'> extends ProtocolBuildStepKindJson
		? string
		: never;

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
	tab_id: StringField<ProtocolBuildTabResultJson, 'tabId'>;
	tab_name: StringField<ProtocolBuildTabResultJson, 'tabName'>;
	status: BuildTabStatus;
	output_id: OptionalStringField<ProtocolBuildTabResultJson, 'outputId'>;
	output_name: OptionalStringField<ProtocolBuildTabResultJson, 'outputName'>;
	error: OptionalStringField<ProtocolBuildTabResultJson, 'error'>;
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
	user_id: OptionalStringField<ProtocolBuildStarterJson, 'userId'>;
	display_name: OptionalStringField<ProtocolBuildStarterJson, 'displayName'>;
	email: OptionalStringField<ProtocolBuildStarterJson, 'email'>;
	triggered_by: OptionalStringField<ProtocolBuildStarterJson, 'triggeredBy'>;
}

export interface BuildResourceConfigSummary {
	max_threads: OptionalNumberField<ProtocolBuildResourceConfigSummaryJson, 'maxThreads'>;
	max_memory_mb: OptionalNumberField<ProtocolBuildResourceConfigSummaryJson, 'maxMemoryMb'>;
	streaming_chunk_size: OptionalNumberField<
		ProtocolBuildResourceConfigSummaryJson,
		'streamingChunkSize'
	>;
}

export interface ActiveBuildSummary {
	build_id: StringField<ProtocolActiveBuildSummaryJson, 'buildId'>;
	analysis_id: StringField<ProtocolActiveBuildSummaryJson, 'analysisId'>;
	analysis_name: StringField<ProtocolActiveBuildSummaryJson, 'analysisName'>;
	namespace: StringField<ProtocolActiveBuildSummaryJson, 'namespace'>;
	status: ActiveBuildStatus;
	started_at: StringField<ProtocolActiveBuildSummaryJson, 'startedAt'>;
	starter: BuildStarter;
	resource_config: BuildResourceConfigSummary | null;
	progress: NumberField<ProtocolActiveBuildSummaryJson, 'progress'>;
	elapsed_ms: NumberField<ProtocolActiveBuildSummaryJson, 'elapsedMs'>;
	estimated_remaining_ms: OptionalNumberField<
		ProtocolActiveBuildSummaryJson,
		'estimatedRemainingMs'
	>;
	current_step: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentStep'>;
	current_step_index: OptionalNumberField<ProtocolActiveBuildSummaryJson, 'currentStepIndex'>;
	total_steps: NumberField<ProtocolActiveBuildSummaryJson, 'totalSteps'>;
	current_kind: EngineRunKind | null;
	current_datasource_id: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentDatasourceId'>;
	current_tab_id: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentTabId'>;
	current_tab_name: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentTabName'>;
	current_output_id: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentOutputId'>;
	current_output_name: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentOutputName'>;
	current_engine_run_id: OptionalStringField<ProtocolActiveBuildSummaryJson, 'currentEngineRunId'>;
	total_tabs: NumberField<ProtocolActiveBuildSummaryJson, 'totalTabs'>;
	cancelled_at: OptionalStringField<ProtocolActiveBuildSummaryJson, 'cancelledAt'>;
	cancelled_by: OptionalStringField<ProtocolActiveBuildSummaryJson, 'cancelledBy'>;
	result_json: OptionalStructHttpField<ProtocolActiveBuildSummaryJson, 'resultJson'>;
}

export interface BuildStepSnapshot {
	build_step_index: NumberField<ProtocolBuildStepSnapshotJson, 'buildStepIndex'>;
	step_index: NumberField<ProtocolBuildStepSnapshotJson, 'stepIndex'>;
	step_id: StringField<ProtocolBuildStepSnapshotJson, 'stepId'>;
	step_name: StringField<ProtocolBuildStepSnapshotJson, 'stepName'>;
	step_type: BuildStepTypeField;
	tab_id: OptionalStringField<ProtocolBuildStepSnapshotJson, 'tabId'>;
	tab_name: OptionalStringField<ProtocolBuildStepSnapshotJson, 'tabName'>;
	state: BuildStepState;
	duration_ms: OptionalNumberField<ProtocolBuildStepSnapshotJson, 'durationMs'>;
	row_count: OptionalInt64HttpNumber<ProtocolBuildStepSnapshotJson, 'rowCount'>;
	error: OptionalStringField<ProtocolBuildStepSnapshotJson, 'error'>;
}

export interface BuildQueryPlanSnapshot {
	tab_id: OptionalStringField<ProtocolBuildQueryPlanSnapshotJson, 'tabId'>;
	tab_name: OptionalStringField<ProtocolBuildQueryPlanSnapshotJson, 'tabName'>;
	optimized_plan: StringField<ProtocolBuildQueryPlanSnapshotJson, 'optimizedPlan'>;
	unoptimized_plan: StringField<ProtocolBuildQueryPlanSnapshotJson, 'unoptimizedPlan'>;
}

export interface BuildResourceSnapshot {
	sampled_at: StringField<ProtocolBuildResourceSnapshotJson, 'sampledAt'>;
	cpu_percent: NumberField<ProtocolBuildResourceSnapshotJson, 'cpuPercent'>;
	memory_mb: NumberField<ProtocolBuildResourceSnapshotJson, 'memoryMb'>;
	memory_limit_mb: OptionalNumberField<ProtocolBuildResourceSnapshotJson, 'memoryLimitMb'>;
	active_threads: NumberField<ProtocolBuildResourceSnapshotJson, 'activeThreads'>;
	max_threads: OptionalNumberField<ProtocolBuildResourceSnapshotJson, 'maxThreads'>;
}

export interface BuildLogEntry {
	timestamp: StringField<ProtocolBuildLogEntryJson, 'timestamp'>;
	level: BuildLogLevel;
	message: StringField<ProtocolBuildLogEntryJson, 'message'>;
	step_name: OptionalStringField<ProtocolBuildLogEntryJson, 'stepName'>;
	step_id: OptionalStringField<ProtocolBuildLogEntryJson, 'stepId'>;
	tab_id: OptionalStringField<ProtocolBuildLogEntryJson, 'tabId'>;
	tab_name: OptionalStringField<ProtocolBuildLogEntryJson, 'tabName'>;
}

export interface ActiveBuildDetail extends ActiveBuildSummary {
	steps: Field<ProtocolActiveBuildDetailJson, 'steps'> extends unknown[]
		? BuildStepSnapshot[]
		: never;
	query_plans: Field<ProtocolActiveBuildDetailJson, 'queryPlans'> extends unknown[]
		? BuildQueryPlanSnapshot[]
		: never;
	latest_resources: BuildResourceSnapshot | null;
	resources: Field<ProtocolActiveBuildDetailJson, 'resources'> extends unknown[]
		? BuildResourceSnapshot[]
		: never;
	logs: Field<ProtocolActiveBuildDetailJson, 'logs'> extends unknown[] ? BuildLogEntry[] : never;
	results: Field<ProtocolActiveBuildDetailJson, 'results'> extends unknown[]
		? BuildTabResult[]
		: never;
	duration_ms: OptionalNumberField<ProtocolActiveBuildDetailJson, 'durationMs'>;
	error: OptionalStringField<ProtocolActiveBuildDetailJson, 'error'>;
	request_json: OptionalStructHttpField<ProtocolActiveBuildDetailJson, 'requestJson'>;
}

export interface BuildDetailSnapshot {
	type: 'snapshot';
	build: ActiveBuildDetail;
	last_sequence?: NumberField<ProtocolBuildSnapshotMessageJson, 'lastSequence'>;
}

export interface BuildsSnapshot {
	type: 'snapshot';
	builds: Field<ProtocolBuildListSnapshotMessageJson, 'builds'> extends unknown[]
		? ActiveBuildSummary[]
		: never;
}

export interface BuildWebsocketErrorMessage {
	type: 'error';
	error: StringField<ProtocolBuildWebsocketErrorMessageJson, 'error'>;
	status_code: NumberField<ProtocolBuildWebsocketErrorMessageJson, 'statusCode'>;
}

export interface ActiveBuildListResponse {
	builds: Field<ProtocolActiveBuildListResponseJson, 'builds'> extends unknown[]
		? ActiveBuildSummary[]
		: never;
	total: NumberField<ProtocolActiveBuildListResponseJson, 'total'>;
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
