import { apiRequest } from '$lib/api/client';

export interface Schedule {
	id: string;
	analysis_id: string;
	cron_expression: string;
	enabled: boolean;
	last_run: string | null;
	next_run: string | null;
	created_at: string;
}

export interface ScheduleCreate {
	analysis_id: string;
	cron_expression: string;
	enabled?: boolean;
}

export interface ScheduleUpdate {
	cron_expression?: string;
	enabled?: boolean;
}

export function listSchedules(analysisId?: string) {
	const params = analysisId ? `?analysis_id=${analysisId}` : '';
	return apiRequest<Schedule[]>(`/v1/schedules${params}`);
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
