import { getTimezoneSettings } from '$lib/utils/datetime';

const TIMESTAMP_SUFFIX_RE = / · [A-Z][a-z]{2} \d{1,2}, \d{4}, \d{2}:\d{2}:\d{2}\.\d{3}( UTC)?$/;

/** Human-readable, millisecond-precise stamp, e.g. `Oct 6, 2026, 14:32:05.123`. */
export function formatAnalysisTimestamp(now: Date, timeZone?: string): string {
	// Assembled from parts: ICU versions disagree on the date/time joiner (", " vs " at ").
	const parts = new Intl.DateTimeFormat('en-US', {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
		fractionalSecondDigits: 3,
		hourCycle: 'h23',
		timeZone
	}).formatToParts(now);
	const part = (type: Intl.DateTimeFormatPartTypes) =>
		parts.find((candidate) => candidate.type === type)?.value ?? '';
	return `${part('month')} ${part('day')}, ${part('year')}, ${part('hour')}:${part('minute')}:${part('second')}.${part('fractionalSecond')}`;
}

/** Names analyses after their creation time so they never collide; replaces any earlier stamp. */
export function timestampedAnalysisName(base: string, now = new Date()): string {
	const { timezone, normalize } = getTimezoneSettings();
	const stem = base.trim().replace(TIMESTAMP_SUFFIX_RE, '');
	return `${stem} · ${formatAnalysisTimestamp(now, normalize ? timezone : undefined)}`;
}
