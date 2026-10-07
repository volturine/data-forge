import { authStore } from '$lib/stores/auth.svelte';
import { localTimeZone, parseInstantWithZone } from '$lib/utils/temporal';

type DateInput = string | number | Temporal.Instant;

const DATE_TIME_INPUT_RE = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/;
const timeZoneValidity = new Map<string, boolean>();

function instantFor(
	value: DateInput,
	timezone: string,
	normalize: boolean
): Temporal.Instant | null {
	return parseInstantWithZone(value, timezone, normalize);
}

function formatInstant(
	value: DateInput,
	timezone: string,
	normalize: boolean,
	options: Intl.DateTimeFormatOptions
): string {
	const instant = instantFor(value, timezone, normalize);
	if (!instant) return String(value);
	const next = normalize ? { ...options, timeZone: timezone } : options;
	return new Intl.DateTimeFormat(undefined, next).format(instant.epochMilliseconds);
}

export function formatDateValue(
	value: DateInput,
	timezone: string,
	normalize: boolean,
	options?: Intl.DateTimeFormatOptions
): string {
	return formatInstant(
		value,
		timezone,
		normalize,
		options ?? { year: 'numeric', month: 'short', day: 'numeric' }
	);
}

export function formatTimeValue(
	value: DateInput,
	timezone: string,
	normalize: boolean,
	options?: Intl.DateTimeFormatOptions
): string {
	return formatInstant(
		value,
		timezone,
		normalize,
		options ?? { hour: '2-digit', minute: '2-digit' }
	);
}

export function getTimezoneSettings(): { timezone: string } {
	const preference = authStore.user?.preferences.timezone;
	if (typeof preference === 'string' && isValidTimeZone(preference)) {
		return { timezone: preference };
	}
	return { timezone: localTimeZone() };
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

export function formatDateDisplay(value: DateInput, options?: Intl.DateTimeFormatOptions): string {
	const { timezone } = getTimezoneSettings();
	return formatDateValue(value, timezone, true, options);
}

export function formatDateTimeDisplay(value: DateInput): string {
	const { timezone } = getTimezoneSettings();
	return formatDateTimeValue(value, timezone, true);
}

export function formatTimeDisplay(value: DateInput, options?: Intl.DateTimeFormatOptions): string {
	const { timezone } = getTimezoneSettings();
	return formatTimeValue(value, timezone, true, options);
}

export function formatDateInput(value: DateInput): string {
	const { timezone } = getTimezoneSettings();
	return formatDateForInput(value, timezone, true);
}

export function getYearDisplay(value: DateInput): number | null {
	const { timezone } = getTimezoneSettings();
	return getYearInZone(value, timezone, true);
}

export function toEpochDisplay(value: DateInput): number {
	const { timezone } = getTimezoneSettings();
	return toEpoch(value, timezone, true);
}

export function formatDateTimeValue(
	value: DateInput,
	timezone: string,
	normalize: boolean
): string {
	return formatInstant(value, timezone, normalize, {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
}

function parseDateTimeInput(value: string): Temporal.PlainDateTime | null {
	const match = DATE_TIME_INPUT_RE.exec(value);
	if (!match) return null;
	try {
		return Temporal.PlainDateTime.from({
			year: Number(match[1].slice(0, 4)),
			month: Number(match[1].slice(5, 7)),
			day: Number(match[1].slice(8, 10)),
			hour: Number(match[2]),
			minute: Number(match[3])
		});
	} catch {
		return null;
	}
}

export function toEpoch(value: DateInput, timezone: string, normalize: boolean): number {
	const instant = instantFor(value, timezone, normalize);
	if (!instant) return Number.NaN;
	return instant.epochMilliseconds;
}

export function formatDateForInput(value: DateInput, timezone: string, normalize: boolean): string {
	if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
	const instant = instantFor(value, timezone, normalize);
	if (!instant) return '';
	if (!normalize) return instant.toString().slice(0, 10);
	return instant.toZonedDateTimeISO(timezone).toPlainDate().toString();
}

export function formatDateTimeForInput(
	value: DateInput,
	timezone: string,
	normalize: boolean
): string {
	const instant = instantFor(value, timezone, normalize);
	if (!instant) return '';
	if (!normalize) return instant.toString().slice(0, 16);
	const zoned = instant.toZonedDateTimeISO(timezone);
	return `${zoned.toPlainDate().toString()}T${String(zoned.hour).padStart(2, '0')}:${String(zoned.minute).padStart(2, '0')}`;
}

export function parseDateTimeInputToIso(
	value: string,
	timezone: string,
	normalize: boolean
): string {
	if (!value) return '';
	if (!normalize) {
		const instant = instantFor(value, timezone, false);
		return instant?.toString() ?? '';
	}
	const parsed = parseDateTimeInput(value);
	if (!parsed) return '';
	return parsed.toZonedDateTime(timezone).toInstant().toString();
}

export function getYearInZone(
	value: DateInput,
	timezone: string,
	normalize: boolean
): number | null {
	const instant = instantFor(value, timezone, normalize);
	if (!instant) return null;
	const zone = normalize ? timezone : localTimeZone();
	return instant.toZonedDateTimeISO(zone).year;
}
