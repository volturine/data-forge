export type BuildEventType =
	| 'plan'
	| 'step_start'
	| 'step_complete'
	| 'step_failed'
	| 'progress'
	| 'resources'
	| 'log'
	| 'complete'
	| 'failed';

export interface BuildEventBase {
	type: BuildEventType;
	build_id: string;
	analysis_id: string;
	emitted_at: string;
	tab_id?: string | null;
	tab_name?: string | null;
	current_output_id?: string | null;
	current_output_name?: string | null;
}

export interface PlanEvent extends BuildEventBase {
	type: 'plan';
	optimized_plan: string;
	unoptimized_plan: string;
}

export interface StepStartEvent extends BuildEventBase {
	type: 'step_start';
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	total_steps: number;
}

export interface StepCompleteEvent extends BuildEventBase {
	type: 'step_complete';
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	duration_ms: number;
	row_count: number | null;
	total_steps: number;
}

export interface StepFailedEvent extends BuildEventBase {
	type: 'step_failed';
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	error: string;
	total_steps: number;
}

export interface ProgressEvent extends BuildEventBase {
	type: 'progress';
	progress: number;
	elapsed_ms: number;
	estimated_remaining_ms: number | null;
	current_step: string | null;
	current_step_index: number | null;
	total_steps: number;
}

export interface ResourcesEvent extends BuildEventBase {
	type: 'resources';
	cpu_percent: number;
	memory_mb: number;
	memory_limit_mb: number | null;
	active_threads: number;
	max_threads: number | null;
}

export interface LogEvent extends BuildEventBase {
	type: 'log';
	level: string;
	message: string;
	step_name: string | null;
	step_id: string | null;
}

export interface CompleteEvent extends BuildEventBase {
	type: 'complete';
	progress: number;
	elapsed_ms: number;
	total_steps: number;
	tabs_built: number;
	results: BuildTabResult[];
	duration_ms: number;
}

export interface FailedEvent extends BuildEventBase {
	type: 'failed';
	progress: number;
	elapsed_ms: number;
	total_steps: number;
	tabs_built: number;
	results: BuildTabResult[];
	duration_ms: number;
	error: string | null;
}

export type BuildEvent =
	| PlanEvent
	| StepStartEvent
	| StepCompleteEvent
	| StepFailedEvent
	| ProgressEvent
	| ResourcesEvent
	| LogEvent
	| CompleteEvent
	| FailedEvent;

export interface BuildTabResult {
	tab_id: string;
	tab_name: string;
	status: 'success' | 'failed';
	output_id?: string | null;
	output_name?: string | null;
	error?: string | null;
}

export type BuildStatus = 'connecting' | 'running' | 'completed' | 'failed' | 'disconnected';

export type BuildStepState = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface StepInfo {
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
}

export interface QueryPlan {
	tabId: string | null;
	tabName: string | null;
	optimized: string;
	unoptimized: string;
}

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
	level: string;
	message: string;
	step_name: string | null;
	step_id: string | null;
	tab_id: string | null;
	tab_name: string | null;
}

export interface ActiveBuildSummary {
	build_id: string;
	analysis_id: string;
	analysis_name: string;
	namespace: string;
	status: string;
	started_at: string;
	starter: BuildStarter;
	resource_config: BuildResourceConfigSummary | null;
	progress: number;
	elapsed_ms: number;
	estimated_remaining_ms: number | null;
	current_step: string | null;
	current_step_index: number | null;
	total_steps: number;
	current_tab_id: string | null;
	current_tab_name: string | null;
	current_output_id: string | null;
	current_output_name: string | null;
	total_tabs: number;
}

export interface ActiveBuildDetail extends ActiveBuildSummary {
	steps: BuildStepSnapshotWire[];
	query_plans: BuildQueryPlanSnapshotWire[];
	latest_resources: BuildResourceSnapshot | null;
	resources: BuildResourceSnapshot[];
	logs: BuildLogEntry[];
	results: BuildTabResult[];
	duration_ms: number | null;
	error: string | null;
}

export interface BuildStepSnapshotWire {
	build_step_index: number;
	step_index: number;
	step_id: string;
	step_name: string;
	step_type: string;
	tab_id: string | null;
	tab_name: string | null;
	state: string;
	duration_ms: number | null;
	row_count: number | null;
	error: string | null;
}

export interface BuildQueryPlanSnapshotWire {
	tab_id: string | null;
	tab_name: string | null;
	optimized_plan: string;
	unoptimized_plan: string;
}

export interface BuildsSnapshot {
	type: 'snapshot';
	builds: ActiveBuildSummary[];
}

export interface BuildDetailSnapshot {
	type: 'snapshot';
	build: ActiveBuildDetail;
}
