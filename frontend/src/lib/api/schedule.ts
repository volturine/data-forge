import { apiRequest } from '$lib/api/client';

export interface Schedule {
	id: string;
	datasource_id: string;
	trigger_on_datasource_id?: string | null;
	cron_expression: string;
	enabled: boolean;
	depends_on: string | null;
	last_run: string | null;
	next_run: string | null;
	created_at: string;
	// Resolved from datasource provenance
	analysis_id?: string | null;
	analysis_name?: string | null;
	tab_id?: string | null;
	tab_name?: string | null;
}

export interface ScheduleCreate {
	datasource_id: string; // REQUIRED - target dataset to build
	cron_expression: string;
	enabled?: boolean;
	depends_on?: string;
	trigger_on_datasource_id?: string;
}

export interface ScheduleUpdate {
	cron_expression?: string;
	enabled?: boolean;
	datasource_id?: string;
	depends_on?: string | null;
	trigger_on_datasource_id?: string | null;
}

export function listSchedules(datasourceId?: string) {
	const params = new URLSearchParams();
	if (datasourceId) params.set('datasource_id', datasourceId);
	const qs = params.toString();
	return apiRequest<Schedule[]>(`/v1/schedules${qs ? `?${qs}` : ''}`);
}

export function createSchedule(payload: ScheduleCreate) {
	return apiRequest<Schedule>('/v1/schedules', {
		method: 'POST',
		body: JSON.stringify(payload)
	});
}

export function updateSchedule(scheduleId: string, payload: ScheduleUpdate) {
	return apiRequest<Schedule>(`/v1/schedules/${scheduleId}`, {
		method: 'PUT',
		body: JSON.stringify(payload)
	});
}

export function deleteSchedule(scheduleId: string) {
	return apiRequest<void>(`/v1/schedules/${scheduleId}`, {
		method: 'DELETE'
	});
}
