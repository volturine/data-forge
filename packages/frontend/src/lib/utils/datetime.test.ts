import { afterEach, beforeEach, describe, test, expect } from 'vitest';
import type { UserPublic } from '#lib/api/auth.js';
import { authStore } from '#lib/stores/auth.svelte.js';
import { localTimeZone } from '#lib/utils/temporal.js';
import {
	formatDateDisplay,
	formatDateTimeDisplay,
	formatDateInput,
	getYearDisplay,
	getTimezoneSettings,
	isValidTimeZone,
	toEpochDisplay,
	formatTimeDisplay
} from './datetime';

const NOON_UTC = Temporal.Instant.from('2024-06-15T12:00:00Z');
const MIDNIGHT_UTC = Temporal.Instant.from('2024-06-15T00:00:00Z');
const previousUser = authStore.user;

function userWithTimezone(timezone: string): UserPublic {
	return {
		id: 'user-1',
		email: 'test@example.com',
		display_name: 'Test User',
		avatar_url: null,
		status: 'active',
		email_verified: true,
		has_password: true,
		preferences: { timezone },
		providers: [],
		created_at: '2026-01-01T00:00:00Z'
	};
}

function useTimezone(timezone: string): void {
	authStore.user = userWithTimezone(timezone);
}

beforeEach(() => {
	useTimezone('UTC');
});

afterEach(() => {
	authStore.user = previousUser;
});

describe('getTimezoneSettings', () => {
	test('uses the saved user timezone for frontend date displays', () => {
		useTimezone('America/Los_Angeles');

		expect(getTimezoneSettings()).toBe('America/Los_Angeles');
		const timestamp = '2026-10-06T21:11:15Z';
		const expected = new Intl.DateTimeFormat(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			hour12: false,
			timeZone: 'America/Los_Angeles'
		}).format(Date.parse(timestamp));
		expect(formatDateTimeDisplay(timestamp)).toBe(expected);
	});

	test('falls back to the browser timezone if no preference is saved', () => {
		authStore.user = null;
		expect(getTimezoneSettings()).toBe(localTimeZone());
	});

	test('falls back to the browser timezone for an invalid saved preference', () => {
		useTimezone('Mars/Phobos');

		expect(getTimezoneSettings()).toBe(localTimeZone());
	});

	test('rejects unsupported IANA timezones', () => {
		const timezone = 'Invalid/TimezoneCacheRegression';
		expect(isValidTimeZone(timezone)).toBe(false);
		expect(isValidTimeZone(timezone)).toBe(false);
	});
});

// ── toEpochDisplay ──────────────────────────────────────────────────────────

describe('toEpochDisplay', () => {
	test('returns epoch milliseconds for Temporal instants', () => {
		expect(toEpochDisplay(NOON_UTC)).toBe(NOON_UTC.epochMilliseconds);
	});

	test('parses timezone-aware strings', () => {
		expect(toEpochDisplay('2024-06-15T12:00:00Z')).toBe(NOON_UTC.epochMilliseconds);
	});

	test('applies timezone to naive ISO strings', () => {
		expect(toEpochDisplay('2024-06-15T12:00:00')).toBe(NOON_UTC.epochMilliseconds);
	});

	test('keeps timezone-aware strings as the same instant in another timezone', () => {
		useTimezone('America/New_York');
		expect(toEpochDisplay('2024-06-15T12:00:00Z')).toBe(NOON_UTC.epochMilliseconds);
	});

	test('UTC offset timestamps keep the same instant in a non-UTC timezone', () => {
		useTimezone('Europe/Bratislava');
		const timestamp = '2026-10-06T21:11:15+00:00';
		expect(toEpochDisplay(timestamp)).toBe(Date.parse(timestamp));
	});

	test('handles date-only strings', () => {
		expect(toEpochDisplay('2024-06-15')).toBe(MIDNIGHT_UTC.epochMilliseconds);
	});

	test('returns NaN for non-ISO strings', () => {
		expect(Number.isNaN(toEpochDisplay('Jun 15, 2024'))).toBe(true);
	});
});

// ── formatDateDisplay ───────────────────────────────────────────────────────

describe('formatDateDisplay', () => {
	test('returns string representation for invalid date', () => {
		expect(formatDateDisplay('not-a-date')).toBe('not-a-date');
	});

	test('uses locale date formatting without options', () => {
		const result = formatDateDisplay('2024-06-15');
		expect(typeof result).toBe('string');
		expect(result.length).toBeGreaterThan(0);
	});

	test('formats in the user timezone', () => {
		const result = formatDateDisplay('2024-06-15T00:00:00Z');
		expect(typeof result).toBe('string');
		expect(result).toContain('2024');
	});

	test('accepts Temporal instants', () => {
		const result = formatDateDisplay(Temporal.Instant.from('2024-01-01T00:00:00Z'));
		expect(result).toContain('2024');
	});

	test('accepts numeric timestamps', () => {
		const result = formatDateDisplay(MIDNIGHT_UTC.epochMilliseconds);
		expect(result).toContain('2024');
	});
});

// ── formatTimeDisplay ───────────────────────────────────────────────────────

describe('formatTimeDisplay', () => {
	test('returns string for invalid date', () => {
		expect(formatTimeDisplay('invalid')).toBe('invalid');
	});

	test('formats time-only output', () => {
		const result = formatTimeDisplay('2024-06-15T14:30:00Z');
		expect(result).toMatch(/\d{2}:\d{2}/);
	});
});

// ── formatDateTimeDisplay ───────────────────────────────────────────────────

describe('formatDateTimeDisplay', () => {
	test('returns string for invalid date', () => {
		expect(formatDateTimeDisplay('invalid')).toBe('invalid');
	});

	test('formats in the user timezone', () => {
		const result = formatDateTimeDisplay('2024-06-15T14:30:00Z');
		expect(typeof result).toBe('string');
		expect(result).toContain('2024');
	});
});

// ── formatDateInput ─────────────────────────────────────────────────────────

describe('formatDateInput', () => {
	test('returns YYYY-MM-DD string as-is', () => {
		expect(formatDateInput('2024-06-15')).toBe('2024-06-15');
	});

	test('returns empty string for invalid date', () => {
		expect(formatDateInput('not-a-date')).toBe('');
	});

	test('returns the ISO date in the user timezone', () => {
		expect(formatDateInput('2024-06-15T12:00:00Z')).toBe('2024-06-15');
	});

	test('returns date in target timezone', () => {
		expect(formatDateInput('2024-06-15T00:00:00Z')).toBe('2024-06-15');
	});
});

// ── getYearDisplay ──────────────────────────────────────────────────────────

describe('getYearDisplay', () => {
	test('returns null for invalid date', () => {
		expect(getYearDisplay('not-a-date')).toBeNull();
	});

	test('returns year in the user timezone for numeric timestamps', () => {
		expect(getYearDisplay(MIDNIGHT_UTC.epochMilliseconds)).toBe(2024);
	});

	test('returns year in target timezone', () => {
		expect(getYearDisplay('2024-01-01T00:00:00Z')).toBe(2024);
	});

	test('handles year boundary with timezone', () => {
		useTimezone('Pacific/Auckland');
		expect(getYearDisplay('2024-01-01T02:00:00Z')).toBe(2024);
	});

	test('accepts numeric timestamp', () => {
		expect(getYearDisplay(MIDNIGHT_UTC.epochMilliseconds)).toBe(2024);
	});
});
