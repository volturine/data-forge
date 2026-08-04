import { describe, expect, it } from 'vitest';
import { elapsedSince, formatDuration } from './format-duration';

describe('formatDuration', () => {
	it('formats null and negative as dash', () => {
		expect(formatDuration(null)).toBe('-');
		expect(formatDuration(undefined)).toBe('-');
		expect(formatDuration(-1)).toBe('-');
	});

	it('formats sub-second durations as ms', () => {
		expect(formatDuration(0)).toBe('0ms');
		expect(formatDuration(120)).toBe('120ms');
		expect(formatDuration(999)).toBe('999ms');
	});

	it('formats seconds with one decimal under 10s', () => {
		expect(formatDuration(1200)).toBe('1.2s');
		expect(formatDuration(9500)).toBe('9.5s');
	});

	it('formats whole seconds from 10s to under a minute', () => {
		expect(formatDuration(45000)).toBe('45s');
		expect(formatDuration(59000)).toBe('59s');
	});

	it('formats minutes and hours', () => {
		expect(formatDuration(135_000)).toBe('2m 15s');
		expect(formatDuration(120_000)).toBe('2m');
		expect(formatDuration(3_780_000)).toBe('1h 3m');
		expect(formatDuration(3_600_000)).toBe('1h');
	});
});

describe('elapsedSince', () => {
	it('returns zero for invalid timestamps', () => {
		expect(elapsedSince('not-a-date')).toBe(0);
	});

	it('computes elapsed ms from started_at', () => {
		const started = new Date('2026-01-01T00:00:00.000Z').toISOString();
		const now = Date.parse('2026-01-01T00:00:05.000Z');
		expect(elapsedSince(started, now)).toBe(5000);
	});
});
