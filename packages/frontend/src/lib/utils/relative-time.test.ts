import { describe, expect, it } from 'vitest';
import { formatRelativeTime } from './relative-time';

const NOW = Date.parse('2026-06-01T12:00:00.000Z');

describe('formatRelativeTime', () => {
	it('returns null for invalid inputs', () => {
		expect(formatRelativeTime(NaN, NOW)).toBeNull();
		expect(formatRelativeTime(Infinity, NOW)).toBeNull();
		expect(formatRelativeTime(NOW, NaN)).toBeNull();
	});

	it('formats sub-minute as just now', () => {
		expect(formatRelativeTime(NOW, NOW)).toBe('just now');
		expect(formatRelativeTime(NOW - 59_000, NOW)).toBe('just now');
	});

	it('formats minutes with correct pluralization', () => {
		expect(formatRelativeTime(NOW - 60_000, NOW)).toBe('1 minute ago');
		expect(formatRelativeTime(NOW - 5 * 60_000, NOW)).toBe('5 minutes ago');
		expect(formatRelativeTime(NOW - 59 * 60_000, NOW)).toBe('59 minutes ago');
	});

	it('formats hours with correct pluralization', () => {
		expect(formatRelativeTime(NOW - 60 * 60_000, NOW)).toBe('1 hour ago');
		expect(formatRelativeTime(NOW - 3 * 60 * 60_000, NOW)).toBe('3 hours ago');
		expect(formatRelativeTime(NOW - 23 * 60 * 60_000, NOW)).toBe('23 hours ago');
	});

	it('formats days', () => {
		expect(formatRelativeTime(NOW - 1 * 24 * 60 * 60_000, NOW)).toBe('1 day ago');
		expect(formatRelativeTime(NOW - 6 * 24 * 60 * 60_000, NOW)).toBe('6 days ago');
	});

	it('formats weeks', () => {
		expect(formatRelativeTime(NOW - 7 * 24 * 60 * 60_000, NOW)).toBe('1 week ago');
		expect(formatRelativeTime(NOW - 21 * 24 * 60 * 60_000, NOW)).toBe('3 weeks ago');
	});

	it('returns null at 30 days and beyond for absolute fallback', () => {
		expect(formatRelativeTime(NOW - 29 * 24 * 60 * 60_000, NOW)).toBe('4 weeks ago');
		expect(formatRelativeTime(NOW - 30 * 24 * 60 * 60_000, NOW)).toBeNull();
		expect(formatRelativeTime(NOW - 90 * 24 * 60 * 60_000, NOW)).toBeNull();
	});
});
