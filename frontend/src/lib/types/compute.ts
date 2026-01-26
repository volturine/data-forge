export type EngineStatus = 'healthy' | 'terminated';

export interface EngineStatusResponse {
	analysis_id: string;
	status: EngineStatus;
	process_id: number | null;
	last_activity: string | null;
	current_job_id: string | null;
}

export interface EngineListResponse {
	engines: EngineStatusResponse[];
}
