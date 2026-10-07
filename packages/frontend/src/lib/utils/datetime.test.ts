import { afterEach, describe, test, expect } from 'vitest';
import type { UserPublic } from '$lib/api/auth';
import { authStore } from '$lib/stores/auth.svelte';
import { localTimeZone } from '$lib/utils/temporal';
import {
	formatDateValue,
	formatDateTimeValue,
	formatDateTimeDisplay,
	formatDateForInput,
	formatDateTimeForInput,
	parseDateTimeInputToIso,
	getYearInZone,
	getTimezoneSettings,
	isValidTimeZone,
	toEpoch,
	formatTimeValue
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

afterEach(() => {
	authStore.user = previousUser;
});

describe('getTimezoneSettings', () => {
	test('uses the saved user timezone for frontend date displays', () => {
		authStore.user = userWithTimezone('America/Los_Angeles');

		expect(getTimezoneSettings()).toEqual({ timezone: 'America/Los_Angeles' });
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
		expect(getTimezoneSettings()).toEqual({ timezone: localTimeZone() });
	});

	test('falls back to the browser timezone for an invalid saved preference', () => {
		authStore.user = userWithTimezone('Mars/Phobos');

		expect(getTimezoneSettings()).toEqual({ timezone: localTimeZone() });
	});

	test('rejects unsupported IANA timezones', () => {
		const timezone = 'Invalid/TimezoneCacheRegression';
		expect(isValidTimeZone(timezone)).toBe(false);
		expect(isValidTimeZone(timezone)).toBe(false);
	});
});

// ── toEpoch ─────────────────────────────────────────────────────────────────

describe('toEpoch', () => {
	test('returns epoch milliseconds for Temporal instants regardless of normalize', () => {
		expect(toEpoch(NOON_UTC, 'UTC', true)).toBe(NOON_UTC.epochMilliseconds);
		expect(toEpoch(NOON_UTC, 'UTC', false)).toBe(NOON_UTC.epochMilliseconds);
	});

	test('non-normalize mode parses timezone-aware values', () => {
		const result = toEpoch('2024-06-15T12:00:00Z', 'UTC', false);
		expect(result).toBe(NOON_UTC.epochMilliseconds);
	});

	test('normalize mode applies timezone to naive ISO strings', () => {
		const utcResult = toEpoch('2024-06-15T12:00:00', 'UTC', true);
		expect(utcResult).toBe(NOON_UTC.epochMilliseconds);
	});

	test('normalize mode passes through timezone-aware strings', () => {
		const result = toEpoch('2024-06-15T12:00:00Z', 'America/New_York', true);
		expect(result).toBe(NOON_UTC.epochMilliseconds);
	});

	test('UTC offset timestamps keep the same instant in a non-UTC timezone', () => {
		const timestamp = '2026-10-06T21:11:15+00:00';
		expect(toEpoch(timestamp, 'Europe/Bratislava', false)).toBe(Date.parse(timestamp));
	});

	test('handles date-only strings', () => {
		const result = toEpoch('2024-06-15', 'UTC', true);
		expect(result).toBe(MIDNIGHT_UTC.epochMilliseconds);
	});

	test('returns NaN for non-ISO strings', () => {
		const result = toEpoch('Jun 15, 2024', 'UTC', true);
		expect(Number.isNaN(result)).toBe(true);
	});
});

// ── formatDateValue ─────────────────────────────────────────────────────────

describe('formatDateValue', () => {
	test('returns string representation for invalid date', () => {
		expect(formatDateValue('not-a-date', 'UTC', false)).toBe('not-a-date');
	});

	test('non-normalize mode without options uses locale date formatting', () => {
		const result = formatDateValue('2024-06-15', 'UTC', false);
		expect(typeof result).toBe('string');
		expect(result.length).toBeGreaterThan(0);
	});

	test('normalize mode with timezone formats correctly', () => {
		const result = formatDateValue('2024-06-15T00:00:00Z', 'UTC', true);
		expect(typeof result).toBe('string');
		expect(result).toContain('2024');
	});

	test('accepts Temporal instants', () => {
		const result = formatDateValue(Temporal.Instant.from('2024-01-01T00:00:00Z'), 'UTC', true);
		expect(result).toContain('2024');
	});

	test('accepts numeric timestamps', () => {
		const result = formatDateValue(MIDNIGHT_UTC.epochMilliseconds, 'UTC', true);
		expect(result).toContain('2024');
	});
});

// ── formatTimeValue ─────────────────────────────────────────────────────────

describe('formatTimeValue', () => {
	test('returns string for invalid date', () => {
		expect(formatTimeValue('invalid', 'UTC', false)).toBe('invalid');
	});

	test('formats time-only output', () => {
		const result = formatTimeValue('2024-06-15T14:30:00Z', 'UTC', true);
		expect(result).toMatch(/\d{2}:\d{2}/);
	});
});

// ── formatDateTimeValue ─────────────────────────────────────────────────────

describe('formatDateTimeValue', () => {
	test('returns string for invalid date', () => {
		expect(formatDateTimeValue('invalid', 'UTC', false)).toBe('invalid');
	});

	test('non-normalize uses locale date/time formatting', () => {
		const result = formatDateTimeValue('2024-06-15T14:30:00Z', 'UTC', false);
		expect(typeof result).toBe('string');
	});

	test('normalize uses timezone', () => {
		const result = formatDateTimeValue('2024-06-15T14:30:00Z', 'UTC', true);
		expect(typeof result).toBe('string');
		expect(result).toContain('2024');
	});
});

// ── formatDateForInput ──────────────────────────────────────────────────────

describe('formatDateForInput', () => {
	test('returns YYYY-MM-DD string as-is', () => {
		expect(formatDateForInput('2024-06-15', 'UTC', false)).toBe('2024-06-15');
	});

	test('returns empty string for invalid date', () => {
		expect(formatDateForInput('not-a-date', 'UTC', false)).toBe('');
	});

	test('non-normalize returns ISO slice', () => {
		const result = formatDateForInput('2024-06-15T12:00:00Z', 'UTC', false);
		expect(result).toBe('2024-06-15');
	});

	test('normalize returns date in target timezone', () => {
		const result = formatDateForInput('2024-06-15T00:00:00Z', 'UTC', true);
		expect(result).toBe('2024-06-15');
	});
});

// ── formatDateTimeForInput ──────────────────────────────────────────────────

describe('formatDateTimeForInput', () => {
	test('returns empty string for invalid date', () => {
		expect(formatDateTimeForInput('not-a-date', 'UTC', false)).toBe('');
	});

	test('non-normalize returns ISO datetime-local format', () => {
		const result = formatDateTimeForInput('2024-06-15T14:30:00Z', 'UTC', false);
		expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
	});

	test('normalize applies timezone conversion', () => {
		const result = formatDateTimeForInput('2024-06-15T00:00:00Z', 'UTC', true);
		expect(result).toBe('2024-06-15T00:00');
	});
});

// ── parseDateTimeInputToIso ─────────────────────────────────────────────────

describe('parseDateTimeInputToIso', () => {
	test('returns empty string for empty input', () => {
		expect(parseDateTimeInputToIso('', 'UTC', false)).toBe('');
	});

	test('non-normalize produces ISO string', () => {
		const result = parseDateTimeInputToIso('2024-06-15T14:30', 'UTC', false);
		expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/);
	});

	test('normalize mode returns empty for invalid format', () => {
		expect(parseDateTimeInputToIso('not-valid', 'UTC', true)).toBe('');
	});

	test('normalize mode with UTC produces correct ISO', () => {
		const result = parseDateTimeInputToIso('2024-06-15T14:30', 'UTC', true);
		expect(result).toBe('2024-06-15T14:30:00Z');
	});

	test('interprets local date-time input in the selected zone and sends a UTC instant', () => {
		const result = parseDateTimeInputToIso('2024-06-15T14:30', 'America/Los_Angeles', true);
		expect(result).toBe('2024-06-15T21:30:00Z');
	});

	test('round-trips through formatDateTimeForInput', () => {
		const original = '2024-06-15T14:30:00Z';
		const formatted = formatDateTimeForInput(original, 'UTC', true);
		const parsed = parseDateTimeInputToIso(formatted, 'UTC', true);
		expect(parsed).toBe(original);
	});

	test('round-trips midnight values without 24:00 formatting', () => {
		const original = '2024-06-15T00:00:00Z';
		const formatted = formatDateTimeForInput(original, 'UTC', true);
		expect(formatted).toBe('2024-06-15T00:00');
		const parsed = parseDateTimeInputToIso(formatted, 'UTC', true);
		expect(parsed).toBe(original);
	});
});

// ── getYearInZone ───────────────────────────────────────────────────────────

describe('getYearInZone', () => {
	test('returns null for invalid date', () => {
		expect(getYearInZone('not-a-date', 'UTC', false)).toBeNull();
	});

	test('non-normalize returns local year', () => {
		expect(getYearInZone(MIDNIGHT_UTC.epochMilliseconds, 'UTC', false)).toBeTypeOf('number');
	});

	test('normalize returns year in target timezone', () => {
		expect(getYearInZone('2024-01-01T00:00:00Z', 'UTC', true)).toBe(2024);
	});

	test('handles year boundary with timezone', () => {
		const result = getYearInZone('2024-01-01T02:00:00Z', 'Pacific/Auckland', true);
		expect(result).toBe(2024);
	});

	test('accepts numeric timestamp', () => {
		expect(getYearInZone(MIDNIGHT_UTC.epochMilliseconds, 'UTC', true)).toBe(2024);
	});
});
