import type { Schedule } from '$lib/api/schedule';
import type { DataSource } from '$lib/types/datasource';
import { formatDateTimeDisplay } from '$lib/utils/datetime';

export function getTriggerType(schedule: Schedule): 'cron' | 'depends' | 'event' {
	if (schedule.trigger_on_datasource_id) return 'event';
	if (schedule.depends_on) return 'depends';
	return 'cron';
}

export function getTriggerLabel(type: 'cron' | 'depends' | 'event'): string {
	if (type === 'cron') return 'Cron';
	if (type === 'depends') return 'Depends';
	return 'Event';
}

const CRON_PATTERNS: Record<string, string> = {
	'0 * * * *': 'Every hour',
	'0 0 * * *': 'Daily at midnight',
	'0 12 * * *': 'Daily at noon',
	'0 0 * * 0': 'Weekly on Sunday',
	'0 0 1 * *': 'Monthly on the 1st',
	'*/5 * * * *': 'Every 5 minutes',
	'*/15 * * * *': 'Every 15 minutes',
	'*/30 * * * *': 'Every 30 minutes',
	'0 9 * * 1': 'Weekly on Monday at 9am',
	'0 17 * * 5': 'Weekly on Friday at 5pm'
};

export function getCronDescription(cron: string): string {
	return CRON_PATTERNS[cron] ?? `Cron: ${cron}`;
}

// Lookups may reference hidden datasources (existing schedules); callers pass
// the full lookup list including hidden entries.
export function resolveDatasource(id: string | null, datasources: DataSource[]): string {
	if (!id) return '-';
	const ds = datasources.find((d) => d.id === id);
	if (!ds) return id.slice(0, 8) + '...';
	return ds.name;
}

export function getTriggerDescription(
	schedule: Schedule,
	datasources: DataSource[],
	allSchedules: Schedule[]
): string {
	const type = getTriggerType(schedule);
	if (type === 'event') {
		const dsId = schedule.trigger_on_datasource_id;
		const dsName = dsId
			? (datasources.find((ds) => ds.id === dsId)?.name ?? dsId.slice(0, 8) + '...')
			: 'Unknown';
		return `When ${dsName} updates`;
	}
	if (type === 'depends') {
		const depId = schedule.depends_on;
		const depSched = allSchedules.find((s) => s.id === depId);
		const depName = depSched
			? (depSched.analysis_name ?? depSched.analysis_id?.slice(0, 8) + '...')
			: depId?.slice(0, 8) + '...';
		return `After "${depName}" completes`;
	}
	return getCronDescription(schedule.cron_expression);
}

export function depOptions(allSchedules: Schedule[], exclude?: string): Schedule[] {
	return allSchedules.filter((s) => s.id !== exclude);
}

export function depLabel(id: string, allSchedules: Schedule[]): string {
	const sched = allSchedules.find((s) => s.id === id);
	if (!sched) return id.slice(0, 8) + '...';
	const name =
		sched.analysis_name ?? (sched.analysis_id ? sched.analysis_id.slice(0, 8) + '...' : 'Unknown');
	const label = `${name} (${sched.cron_expression})`;
	return label.length > 40 ? `${label.slice(0, 39)}…` : label;
}

export function formatDate(iso: string | null): string {
	if (!iso) return '-';
	return formatDateTimeDisplay(iso);
}

export function getProvenanceDisplay(schedule: Schedule): string {
	if (schedule.analysis_name && schedule.tab_name) {
		return `${schedule.analysis_name} → ${schedule.tab_name}`;
	}
	if (schedule.analysis_name) {
		return schedule.analysis_name;
	}
	if (schedule.analysis_id) {
		return schedule.analysis_id.slice(0, 8) + '...';
	}
	return 'Unknown';
}
