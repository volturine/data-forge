export type FreshnessStatus = 'fresh' | 'stale' | 'outdated' | 'unknown';

/** Applied when a datasource has no explicit freshness threshold. */
export const DEFAULT_FRESHNESS_THRESHOLD_MINUTES = 24 * 60;

const HALF_THRESHOLD = 0.5;

/**
 * Classify data freshness relative to its configured threshold.
 *
 * - `fresh`: last update is within half the threshold.
 * - `stale`: within the threshold but past the halfway mark.
 * - `outdated`: past the threshold.
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
	if (ageMs < thresholdMs * HALF_THRESHOLD) return 'fresh';
	if (ageMs < thresholdMs) return 'stale';
	return 'outdated';
}
