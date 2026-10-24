import { authStore } from '#lib/stores/auth.svelte.js';
import { localTimeZone, parseInstantWithZone, type TemporalInput } from '#lib/utils/temporal.js';

const timeZoneValidity = new Map<string, boolean>();

function formatInstant(
	value: TemporalInput,
	timezone: string,
	options: Intl.DateTimeFormatOptions
): string {
	const instant = parseInstantWithZone(value, timezone, true);
	if (!instant) return String(value);
	const next = { ...options, timeZone: timezone };
	return new Intl.DateTimeFormat(undefined, next).format(instant.epochMilliseconds);
}

export function formatDateDisplay(
	value: TemporalInput,
	options?: Intl.DateTimeFormatOptions
): string {
	return formatInstant(
		value,
		getTimezoneSettings(),
		options ?? { year: 'numeric', month: 'short', day: 'numeric' }
	);
}

export function formatTimeDisplay(
	value: TemporalInput,
	options?: Intl.DateTimeFormatOptions
): string {
	return formatInstant(
		value,
		getTimezoneSettings(),
		options ?? { hour: '2-digit', minute: '2-digit' }
	);
}

export function getTimezoneSettings(): string {
	const preference = authStore.user?.preferences.timezone;
	if (typeof preference === 'string' && isValidTimeZone(preference)) return preference;
	return localTimeZone();
}

export function isValidTimeZone(timezone: string): boolean {
	const cached = timeZoneValidity.get(timezone);
	if (cached !== undefined) return cached;

	let valid = true;
	try {
		new Intl.DateTimeFormat(undefined, { timeZone: timezone });
	} catch {
		valid = false;
	}
	timeZoneValidity.set(timezone, valid);
	return valid;
}

export function formatDateTimeDisplay(value: TemporalInput): string {
	return formatInstant(value, getTimezoneSettings(), {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
}

export function toEpochDisplay(value: TemporalInput): number {
	const instant = parseInstantWithZone(value, getTimezoneSettings(), true);
	if (!instant) return Number.NaN;
	return instant.epochMilliseconds;
}

export function formatDateInput(value: TemporalInput): string {
	if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
	const timezone = getTimezoneSettings();
	const instant = parseInstantWithZone(value, timezone, true);
	if (!instant) return '';
	return instant.toZonedDateTimeISO(timezone).toPlainDate().toString();
}

export function getYearDisplay(value: TemporalInput): number | null {
	const timezone = getTimezoneSettings();
	const instant = parseInstantWithZone(value, timezone, true);
	if (!instant) return null;
	return instant.toZonedDateTimeISO(timezone).year;
}
