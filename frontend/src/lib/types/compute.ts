export type ComputeStatus = 'pending' | 'running' | 'completed' | 'failed';

export type EngineStatus = 'idle' | 'running' | 'error' | 'terminated';

export interface EngineStatusResponse {
	analysis_id: string;
	status: EngineStatus;
	process_id: number | null;
	last_activity: string | null;
}

export interface ComputeJob {
	id: string;
	status: ComputeStatus;
	progress?: number;
	error?: string | null;
	result?: unknown;
	current_step?: string | null;
	created_at?: string;
	updated_at?: string;
}
