export type EngineStatus = 'healthy' | 'terminated';
export type EngineScope = 'datasource_preview' | 'analysis_interactive' | 'build';
export type EngineReusePolicy = 'shared' | 'exclusive';

/**
 * Resource configuration for compute engine.
 * All fields are optional - null/undefined means use default from settings.
 * Value of 0 means auto-detect/unlimited.
 */
export interface EngineResourceConfig {
	max_threads?: number | null; // CPU threads (0 = auto-detect)
	max_memory_mb?: number | null; // Memory limit in MB (0 = unlimited)
	streaming_chunk_size?: number | null; // Streaming chunk size (0 = auto)
}

export interface EngineStatusResponse {
	analysis_id: string;
	resource_id: string;
	status: EngineStatus;
	process_id: number | null;
	last_activity: string | null;
	current_job_id: string | null;
	resource_config: EngineResourceConfig | null; // User-provided overrides
	effective_resources: EngineResourceConfig | null; // Actual values being used
	defaults: EngineDefaults | null; // Default values from env vars
	scope: EngineScope | null;
	reuse_policy: EngineReusePolicy | null;
	datasource_id: string | null;
	build_id: string | null;
	current_build_id: string | null;
	current_engine_run_id: string | null;
}

export interface SpawnEngineRequest {
	resource_config?: EngineResourceConfig | null;
}

export interface EngineIdentityPayload {
	scope: EngineScope;
	reuse_policy: EngineReusePolicy;
	resource_id: string;
	analysis_id?: string | null;
	datasource_id?: string | null;
	build_id?: string | null;
}

export interface EngineDefaults {
	max_threads: number;
	max_memory_mb: number;
	streaming_chunk_size: number;
}
