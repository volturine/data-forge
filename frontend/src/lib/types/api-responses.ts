// Raw API response types (before normalization)

export interface RawComputeJobResponse {
	job_id?: string;
	id?: string;
	status: unknown; // Will be validated to ComputeStatus
	progress?: number;
	error_message?: string;
	error?: string;
	data?: unknown;
	result?: unknown;
	created_at?: string;
	updated_at?: string;
}

export interface HealthResponse {
	status: string;
	timestamp: string;
	version?: string;
}

// Type for table cell values - can be various types
export type TableCellValue = string | number | boolean | null | undefined;
