import { apiRequest } from './client';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export interface HealthCheck {
	id: string;
	datasource_id: string;
	name: string;
	check_type: string;
	config: Record<string, unknown>;
	enabled: boolean;
	created_at: string;
}

export interface HealthCheckCreate {
	datasource_id: string;
	name: string;
	check_type: string;
	config: Record<string, unknown>;
	enabled: boolean;
}

export interface HealthCheckUpdate {
	name?: string;
	check_type?: string;
	config?: Record<string, unknown>;
	enabled?: boolean;
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
