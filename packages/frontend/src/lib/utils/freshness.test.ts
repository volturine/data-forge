import { describe, expect, it } from 'vitest';
import { DEFAULT_FRESHNESS_THRESHOLD_MINUTES, freshnessStatus } from './freshness';

const NOW = Date.parse('2026-06-01T12:00:00.000Z');
const HOUR = 60 * 60_000;

describe('freshnessStatus', () => {
	it('returns unknown when there is no last update', () => {
		expect(freshnessStatus(null, 1440, NOW)).toBe('unknown');
		expect(freshnessStatus(undefined, 1440, NOW)).toBe('unknown');
		expect(freshnessStatus(NaN, 1440, NOW)).toBe('unknown');
		expect(freshnessStatus(Infinity, 1440, NOW)).toBe('unknown');
	});

	it('returns fresh when well within the threshold', () => {
		expect(freshnessStatus(NOW - 1, 1440, NOW)).toBe('fresh');
		expect(freshnessStatus(NOW - 11 * HOUR, 1440, NOW)).toBe('fresh');
	});

	it('returns stale when approaching the threshold', () => {
		expect(freshnessStatus(NOW - 13 * HOUR, 1440, NOW)).toBe('stale');
		expect(freshnessStatus(NOW - 23 * HOUR, 1440, NOW)).toBe('stale');
	});

	it('returns outdated past the threshold', () => {
		expect(freshnessStatus(NOW - 24 * HOUR, 1440, NOW)).toBe('outdated');
		expect(freshnessStatus(NOW - 48 * HOUR, 1440, NOW)).toBe('outdated');
	});

	it('treats a future timestamp as fresh', () => {
		expect(freshnessStatus(NOW + 5 * HOUR, 1440, NOW)).toBe('fresh');
	});

	it('applies the default 24-hour threshold when none is configured', () => {
		expect(DEFAULT_FRESHNESS_THRESHOLD_MINUTES).toBe(24 * 60);
		expect(freshnessStatus(NOW - 23 * HOUR, null, NOW)).toBe('stale');
		expect(freshnessStatus(NOW - 24 * HOUR, null, NOW)).toBe('outdated');
	});

	it('honors an explicit threshold', () => {
		const oneHour = 60;
		expect(freshnessStatus(NOW - 29 * 60_000, oneHour, NOW)).toBe('fresh');
		expect(freshnessStatus(NOW - 30 * 60_000, oneHour, NOW)).toBe('stale');
		expect(freshnessStatus(NOW - 60 * 60_000, oneHour, NOW)).toBe('outdated');
	});
});
