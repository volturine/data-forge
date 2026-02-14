import { apiRequest } from '$lib/api/client';

export interface Schedule {
	id: string;
	analysis_id: string;
	datasource_id: string | null;
	cron_expression: string;
	enabled: boolean;
	depends_on: string | null;
	last_run: string | null;
	next_run: string | null;
	created_at: string;
}

export interface ScheduleCreate {
	analysis_id: string;
	cron_expression: string;
	enabled?: boolean;
	datasource_id?: string;
	depends_on?: string;
}

export interface ScheduleUpdate {
	cron_expression?: string;
	enabled?: boolean;
	datasource_id?: string | null;
	depends_on?: string | null;
}

export function listSchedules(analysisId?: string, datasourceId?: string) {
	const params = new URLSearchParams();
	if (analysisId) params.set('analysis_id', analysisId);
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
	return apiRequest<{ message: string }>(`/v1/schedules/${scheduleId}`, {
		method: 'DELETE'
	});
}
