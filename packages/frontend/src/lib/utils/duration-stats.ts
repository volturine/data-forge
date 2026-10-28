/** Half-window build-length direction (duration down / flat / up / not enough data). */
export type DurationTrendDirection = 'decreasing' | 'stable' | 'increasing' | 'insufficient_data';

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
