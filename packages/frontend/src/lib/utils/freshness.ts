export type FreshnessStatus = 'fresh' | 'stale' | 'outdated' | 'unknown';

/** Applied when a datasource has no explicit freshness threshold. */
export const DEFAULT_FRESHNESS_THRESHOLD_MINUTES = 24 * 60;

/**
 * Classify data freshness relative to its configured threshold.
 *
 * - `fresh`: last update is within the threshold.
 * - `stale`: within twice the threshold but past the threshold.
 * - `outdated`: past twice the threshold.
 * - `unknown`: no last-update timestamp (or an unparseable one).
 */
export function freshnessStatus(
	lastDataUpdateMs: number | null | undefined,
	thresholdMinutes: number | null | undefined,
	nowMs: number = Date.now()
): FreshnessStatus {
	if (lastDataUpdateMs == null || !Number.isFinite(lastDataUpdateMs)) return 'unknown';
	const thresholdMs = (thresholdMinutes ?? DEFAULT_FRESHNESS_THRESHOLD_MINUTES) * 60_000;
	const ageMs = nowMs - lastDataUpdateMs;
	if (ageMs < thresholdMs) return 'fresh';
	if (ageMs < thresholdMs * 2) return 'stale';
	return 'outdated';
}
