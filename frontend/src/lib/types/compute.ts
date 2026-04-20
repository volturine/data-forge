export type EngineStatus = 'healthy' | 'terminated';

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
	status: EngineStatus;
	process_id: number | null;
	last_activity: string | null;
	current_job_id: string | null;
	resource_config: EngineResourceConfig | null; // User-provided overrides
	effective_resources: EngineResourceConfig | null; // Actual values being used
	defaults: EngineDefaults | null; // Default values from env vars
}

export interface SpawnEngineRequest {
	resource_config?: EngineResourceConfig | null;
}

export interface EngineDefaults {
	max_threads: number;
	max_memory_mb: number;
	streaming_chunk_size: number;
}
