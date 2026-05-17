// This file is auto-generated. Do not edit manually. Run 'just generate-build-stream-types' to regenerate.
// Generated from backend/modules/compute/schemas.py

export type EngineRunKind = 'build' | 'preview' | 'row_count' | 'download';

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

export type BuildLogLevel = 'info' | 'warning' | 'error';

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

export type BuildTabStatus = 'success' | 'failed';

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

export type ActiveBuildStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

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

export type BuildStepState = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

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

export interface ActiveBuildDetail {
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
