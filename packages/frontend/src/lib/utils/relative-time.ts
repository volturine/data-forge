const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;
const MONTH_MS = 30 * DAY_MS;

function label(count: number, unit: string): string {
	return `${count} ${unit}${count === 1 ? '' : 's'} ago`;
}

/**
 * Format an epoch-ms timestamp as a relative time label per the freshness PRD.
 *
 * Returns `null` when the timestamp is at least 30 days old — callers should
 * fall back to an absolute date instead of a relative label.
 */
export function formatRelativeTime(timestampMs: number, nowMs: number = Date.now()): string | null {
	if (!Number.isFinite(timestampMs) || !Number.isFinite(nowMs)) return null;
	const elapsedMs = nowMs - timestampMs;
	if (elapsedMs < MINUTE_MS) return 'just now';
	if (elapsedMs < HOUR_MS) return label(Math.floor(elapsedMs / MINUTE_MS), 'minute');
	if (elapsedMs < DAY_MS) return label(Math.floor(elapsedMs / HOUR_MS), 'hour');
	if (elapsedMs < WEEK_MS) return label(Math.floor(elapsedMs / DAY_MS), 'day');
	if (elapsedMs < MONTH_MS) return label(Math.floor(elapsedMs / WEEK_MS), 'week');
	return null;
}
