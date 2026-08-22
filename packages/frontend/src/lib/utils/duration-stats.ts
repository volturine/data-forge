/** Half-window build-length direction (duration down / flat / up / not enough data). */
export type DurationTrendDirection = 'decreasing' | 'stable' | 'increasing' | 'insufficient_data';

export interface DurationTrend {
	direction: DurationTrendDirection;
	/** Signed on duration: positive = increasing, negative = decreasing. */
	change_pct: number | null;
	older_avg_ms: number | null;
	recent_avg_ms: number | null;
	older_count: number;
	recent_count: number;
	sample_size: number;
	threshold_pct: number;
	summary: string;
}

export interface DurationStatsRun {
	id: string;
	started_at: string;
	duration_ms: number | null;
	status: string;
}

export function isSuccessfulBuildStatus(status: string): boolean {
	const normalized = status.toLowerCase();
	return normalized === 'completed' || normalized === 'success';
}

export function trendDirectionLabel(direction: DurationTrendDirection): string {
	if (direction === 'decreasing') return 'Duration decreasing';
	if (direction === 'increasing') return 'Duration increasing';
	if (direction === 'insufficient_data') return 'Not enough data';
	return 'Stable';
}

export function trendTone(direction: DurationTrendDirection): 'success' | 'warning' | 'muted' {
	if (direction === 'decreasing') return 'success';
	if (direction === 'increasing') return 'warning';
	return 'muted';
}
