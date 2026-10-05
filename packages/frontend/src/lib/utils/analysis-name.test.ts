import { describe, expect, test, vi } from 'vitest';
import { timestampedAnalysisName } from './analysis-name';

vi.mock('$lib/utils/datetime', () => ({
	getTimezoneSettings: () => ({ timezone: 'UTC', normalize: true })
}));

const NOW = new Date(Date.UTC(2026, 9, 6, 14, 32, 5, 123));

describe('timestampedAnalysisName', () => {
	test('appends a human-readable millisecond timestamp', () => {
		expect(timestampedAnalysisName('Sensors Analysis', NOW)).toBe(
			'Sensors Analysis · Oct 6, 2026, 14:32:05.123'
		);
	});

	test('replaces an existing timestamp instead of stacking them', () => {
		expect(
			timestampedAnalysisName('Copy of Sensors Analysis · Oct 1, 2026, 09:00:00.001', NOW)
		).toBe('Copy of Sensors Analysis · Oct 6, 2026, 14:32:05.123');
	});

	test('gives distinct names a millisecond apart', () => {
		const later = new Date(NOW.getTime() + 1);
		expect(timestampedAnalysisName('Sensors', NOW)).not.toBe(
			timestampedAnalysisName('Sensors', later)
		);
	});
});
