import { describe, test, expect } from 'vitest';
import type { Schedule } from '$lib/api/schedule';
import type { DataSource } from '$lib/types/datasource';
import {
	depLabel,
	depOptions,
	formatDate,
	getCronDescription,
	getProvenanceDisplay,
	getTriggerDescription,
	getTriggerLabel,
	getTriggerType,
	resolveDatasource
} from './schedule-utils';

function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
	return {
		id: 'sched-1',
		datasource_id: 'ds-1',
		description: null,
		trigger_on_datasource_id: null,
		cron_expression: '0 * * * *',
		enabled: true,
		depends_on: null,
		last_run: null,
		next_run: null,
		created_at: '2026-01-01T00:00:00Z',
		analysis_id: null,
		analysis_name: null,
		tab_id: null,
		tab_name: null,
		...overrides
	};
}

const datasources = [
	{ id: 'ds-1', name: 'Sales Output' },
	{ id: 'ds-hidden', name: 'Hidden Output' }
] as DataSource[];

const allSchedules = [
	makeSchedule({ id: 'sched-1', analysis_name: 'Sales Analysis', cron_expression: '0 * * * *' }),
	makeSchedule({
		id: 'sched-2',
		analysis_id: 'an-abcdef12',
		cron_expression: '*/5 * * * *'
	})
];

describe('getTriggerType', () => {
	test('cron when nothing else set', () => {
		expect(getTriggerType(makeSchedule())).toBe('cron');
	});

	test('depends when depends_on set', () => {
		expect(getTriggerType(makeSchedule({ depends_on: 'sched-2' }))).toBe('depends');
	});

	test('event takes precedence over depends', () => {
		expect(
			getTriggerType(makeSchedule({ depends_on: 'sched-2', trigger_on_datasource_id: 'ds-1' }))
		).toBe('event');
	});
});

describe('getTriggerLabel', () => {
	test('labels each type', () => {
		expect(getTriggerLabel('cron')).toBe('Cron');
		expect(getTriggerLabel('depends')).toBe('Depends');
		expect(getTriggerLabel('event')).toBe('Event');
	});
});

describe('getCronDescription', () => {
	test('known patterns', () => {
		expect(getCronDescription('0 * * * *')).toBe('Every hour');
		expect(getCronDescription('*/15 * * * *')).toBe('Every 15 minutes');
	});

	test('unknown pattern falls back to raw expression', () => {
		expect(getCronDescription('7 4 * * 2')).toBe('Cron: 7 4 * * 2');
	});
});

describe('getTriggerDescription', () => {
	test('cron schedule describes the interval', () => {
		expect(getTriggerDescription(makeSchedule(), datasources, allSchedules)).toBe('Every hour');
	});

	test('event schedule names the triggering datasource', () => {
		const schedule = makeSchedule({ trigger_on_datasource_id: 'ds-1' });
		expect(getTriggerDescription(schedule, datasources, allSchedules)).toBe(
			'When Sales Output updates'
		);
	});

	test('event with unknown datasource truncates the id', () => {
		const schedule = makeSchedule({ trigger_on_datasource_id: 'unknown-id-123' });
		expect(getTriggerDescription(schedule, [], allSchedules)).toBe('When unknown-... updates');
	});

	test('depends schedule names the dependency by analysis name', () => {
		const schedule = makeSchedule({ depends_on: 'sched-1' });
		expect(getTriggerDescription(schedule, datasources, allSchedules)).toBe(
			'After "Sales Analysis" completes'
		);
	});

	test('depends without analysis name falls back to truncated analysis id', () => {
		const schedule = makeSchedule({ depends_on: 'sched-2' });
		expect(getTriggerDescription(schedule, datasources, allSchedules)).toBe(
			'After "an-abcde..." completes'
		);
	});

	test('depends on missing schedule falls back to truncated id', () => {
		const schedule = makeSchedule({ depends_on: 'gone-12345' });
		expect(getTriggerDescription(schedule, datasources, allSchedules)).toBe(
			'After "gone-123..." completes'
		);
	});
});

describe('resolveDatasource', () => {
	test('resolves known id to name', () => {
		expect(resolveDatasource('ds-1', datasources)).toBe('Sales Output');
	});

	test('truncates unknown id', () => {
		expect(resolveDatasource('unknown-id-123', datasources)).toBe('unknown-...');
	});

	test('null id renders dash', () => {
		expect(resolveDatasource(null, datasources)).toBe('-');
	});
});

describe('depOptions / depLabel', () => {
	test('excludes self from dependency options', () => {
		expect(depOptions(allSchedules, 'sched-1').map((s) => s.id)).toEqual(['sched-2']);
	});

	test('label prefers analysis name', () => {
		expect(depLabel('sched-1', allSchedules)).toBe('Sales Analysis (0 * * * *)');
	});

	test('falls back to truncated analysis id then raw id', () => {
		expect(depLabel('sched-2', allSchedules)).toBe('an-abcde... (*/5 * * * *)');
		expect(depLabel('missing', allSchedules)).toBe('missing...');
	});
});

describe('formatDate', () => {
	test('null renders dash', () => {
		expect(formatDate(null)).toBe('-');
	});

	test('formats ISO date', () => {
		expect(formatDate('2026-06-01T12:00:00Z')).toMatch(/2026/);
	});
});

describe('getProvenanceDisplay', () => {
	test('joins analysis and tab names', () => {
		expect(getProvenanceDisplay(makeSchedule({ analysis_name: 'A', tab_name: 'T' }))).toBe('A → T');
	});

	test('prefers analysis name alone', () => {
		expect(getProvenanceDisplay(makeSchedule({ analysis_name: 'A' }))).toBe('A');
	});

	test('falls back to truncated analysis id', () => {
		expect(getProvenanceDisplay(makeSchedule({ analysis_id: 'an-1234567890' }))).toBe(
			'an-12345...'
		);
	});

	test('unknown when nothing available', () => {
		expect(getProvenanceDisplay(makeSchedule())).toBe('Unknown');
	});
});
