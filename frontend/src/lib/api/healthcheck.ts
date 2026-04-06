import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export type CheckType =
	| 'row_count'
	| 'column_null'
	| 'column_unique'
	| 'column_range'
	| 'column_count'
	| 'null_percentage'
	| 'duplicate_percentage';

export interface RowCountConfig {
	min?: number | null;
	max?: number | null;
}

export interface ColumnCheckConfig {
	column: string;
	threshold?: number | null;
}

export interface ColumnRangeConfig {
	column: string;
	min?: number | null;
	max?: number | null;
}

export interface NullPercentageConfig {
	threshold: number;
}

export interface DuplicatePercentageConfig {
	columns?: string[];
	threshold: number;
}

export type HealthCheckConfig =
	| RowCountConfig
	| ColumnCheckConfig
	| ColumnRangeConfig
	| NullPercentageConfig
	| DuplicatePercentageConfig;

export interface HealthCheck {
	id: string;
	datasource_id: string;
	name: string;
	check_type: CheckType;
	config: HealthCheckConfig;
	enabled: boolean;
	critical: boolean;
	created_at: string;
}

export interface HealthCheckCreate {
	datasource_id: string;
	name: string;
	check_type: CheckType;
	config: HealthCheckConfig;
	enabled: boolean;
	critical: boolean;
}

export interface HealthCheckUpdate {
	name?: string;
	check_type?: CheckType;
	config?: HealthCheckConfig;
	enabled?: boolean;
	critical?: boolean;
}

export function listHealthChecks(datasourceId: string): ResultAsync<HealthCheck[], ApiError> {
	return apiRequest<HealthCheck[]>(`/v1/healthchecks?datasource_id=${datasourceId}`);
}

export function createHealthCheck(payload: HealthCheckCreate): ResultAsync<HealthCheck, ApiError> {
	return apiRequest<HealthCheck>('/v1/healthchecks', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}

export function updateHealthCheck(
	id: string,
	payload: HealthCheckUpdate
): ResultAsync<HealthCheck, ApiError> {
	return apiRequest<HealthCheck>(`/v1/healthchecks/${id}`, {
		method: 'PUT',
		body: JSON.stringify(payload)
	});
}

export function deleteHealthCheck(id: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/healthchecks/${id}`, { method: 'DELETE' });
}

export interface HealthCheckResult {
	id: string;
	healthcheck_id: string;
	passed: boolean;
	message: string;
	details: Record<string, unknown>;
	checked_at: string;
}

export function listHealthCheckResults(
	datasourceId: string,
	limit: number = 10
): ResultAsync<HealthCheckResult[], ApiError> {
	return apiRequest<HealthCheckResult[]>(
		`/v1/healthchecks/results?datasource_id=${datasourceId}&limit=${limit}`
	);
}
