// Raw API response types (before normalization)

export interface HealthResponse {
	status: string;
	timestamp: string;
	version?: string;
}

// Type for table cell values - can be various types
export type TableCellValue = string | number | boolean | null | undefined;
