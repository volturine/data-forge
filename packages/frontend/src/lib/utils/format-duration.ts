/** Human-readable duration: `120ms`, `1.2s`, `45s`, `2m 15s`, `1h 3m`. */
export function formatDuration(ms: number | null | undefined): string {
	if (ms === null || ms === undefined || Number.isNaN(ms) || ms < 0) return '-';
	if (ms < 1000) return `${Math.round(ms)}ms`;

	const totalSec = ms / 1000;
	if (totalSec < 60) {
		if (totalSec < 10) return `${totalSec.toFixed(1)}s`;
		return `${Math.round(totalSec)}s`;
	}

	const totalMin = Math.floor(totalSec / 60);
	const sec = Math.round(totalSec % 60);
	if (totalMin < 60) {
		if (sec === 0) return `${totalMin}m`;
		return `${totalMin}m ${sec}s`;
	}

	const hours = Math.floor(totalMin / 60);
	const min = totalMin % 60;
	if (min === 0) return `${hours}h`;
	return `${hours}h ${min}m`;
}

/** Live elapsed ms from an ISO started_at timestamp. */
export function elapsedSince(startedAt: string, nowMs: number = Date.now()): number {
	const started = Date.parse(startedAt);
	if (Number.isNaN(started)) return 0;
	return Math.max(nowMs - started, 0);
}
