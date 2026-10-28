import type { ResultAsync } from 'neverthrow';
import { apiRequest } from './client';
import type { ApiError } from './client';
import { withQuery } from './query';

export interface Schedule {
	id: string;
	datasource_id: string;
	description?: string | null;
	trigger_on_datasource_id?: string | null;
	cron_expression: string;
	enabled: boolean;
	depends_on: string | null;
	last_run: string | null;
	next_run: string | null;
	created_at: string;
	analysis_id?: string | null;
	analysis_name?: string | null;
	tab_id?: string | null;
	tab_name?: string | null;
}

export interface ScheduleCreate {
	datasource_id: string;
	description?: string;
	cron_expression: string;
	enabled?: boolean;
	depends_on?: string;
	trigger_on_datasource_id?: string;
}

export interface ScheduleUpdate {
	cron_expression?: string;
	description?: string | null;
	enabled?: boolean;
	datasource_id?: string;
	depends_on?: string | null;
	trigger_on_datasource_id?: string | null;
}

export interface ListSchedulesParams {
	datasourceId?: string;
	search?: string;
	limit?: number;
	offset?: number;
}

export function listSchedules(params?: ListSchedulesParams): ResultAsync<Schedule[], ApiError> {
	return apiRequest<Schedule[]>(
		withQuery('/v1/schedules', {
			datasource_id: params?.datasourceId,
			search: params?.search,
			limit: params?.limit,
			offset: params?.offset
		})
	);
}

export function createSchedule(payload: ScheduleCreate): ResultAsync<Schedule, ApiError> {
	return apiRequest<Schedule>('/v1/schedules', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}

export function updateSchedule(
	scheduleId: string,
	payload: ScheduleUpdate
): ResultAsync<Schedule, ApiError> {
	return apiRequest<Schedule>(`/v1/schedules/${scheduleId}`, {
		method: 'PUT',
		body: JSON.stringify(payload)
	});
}

export function deleteSchedule(scheduleId: string): ResultAsync<void, ApiError> {
	return apiRequest<void>(`/v1/schedules/${scheduleId}`, {
		method: 'DELETE'
	});
}
