import { configStore } from '$lib/stores/config.svelte';

type DateInput = string | number | Date;

function toDate(value: DateInput): Date | null {
	if (value instanceof Date) {
		const time = value.getTime();
		if (Number.isNaN(time)) return null;
		return value;
	}
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) return null;
	return date;
}

function hasTimezone(value: string): boolean {
	return /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
}

function parseIsoParts(value: string): {
	year: number;
	month: number;
	day: number;
	hour: number;
	minute: number;
	second: number;
	millisecond: number;
} | null {
	const match =
		/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?)?$/.exec(value);
	if (!match) return null;
	const year = Number(match[1]);
	const month = Number(match[2]);
	const day = Number(match[3]);
	const hour = Number(match[4] ?? 0);
	const minute = Number(match[5] ?? 0);
	const second = Number(match[6] ?? 0);
	const millisecond = Number(match[7] ?? 0);
	if (!year || !month || !day) return null;
	return { year, month, day, hour, minute, second, millisecond };
}

export function formatDateValue(
	value: DateInput,
	timezone: string,
	normalize: boolean,
	options?: Intl.DateTimeFormatOptions
): string {
	const date = toDate(value);
	if (!date) return String(value);
	if (!normalize) {
		if (!options) return date.toLocaleDateString();
		return new Intl.DateTimeFormat(undefined, options).format(date);
	}
	const nextOptions = options ?? { year: 'numeric', month: 'short', day: 'numeric' };
	const format = new Intl.DateTimeFormat(undefined, { ...nextOptions, timeZone: timezone });
	return format.format(date);
}

export function getTimezoneSettings(): { timezone: string; normalize: boolean } {
	return { timezone: configStore.timezone, normalize: configStore.normalizeTz };
}

export function formatDateDisplay(value: DateInput, options?: Intl.DateTimeFormatOptions): string {
	const { timezone, normalize } = getTimezoneSettings();
	return formatDateValue(value, timezone, normalize, options);
}

export function formatDateTimeDisplay(value: DateInput): string {
	const { timezone, normalize } = getTimezoneSettings();
	return formatDateTimeValue(value, timezone, normalize);
}

export function formatDateInput(value: DateInput): string {
	const { timezone, normalize } = getTimezoneSettings();
	return formatDateForInput(value, timezone, normalize);
}

export function formatDateTimeInput(value: DateInput): string {
	const { timezone, normalize } = getTimezoneSettings();
	return formatDateTimeForInput(value, timezone, normalize);
}

export function parseDateTimeInputValue(value: string): string {
	const { timezone, normalize } = getTimezoneSettings();
	return parseDateTimeInputToIso(value, timezone, normalize);
}

export function getYearDisplay(value: DateInput): number | null {
	const { timezone, normalize } = getTimezoneSettings();
	return getYearInZone(value, timezone, normalize);
}

export function toEpochDisplay(value: DateInput): number {
	const { timezone, normalize } = getTimezoneSettings();
	return toEpoch(value, timezone, normalize);
}

export function formatDateTimeValue(
	value: DateInput,
	timezone: string,
	normalize: boolean
): string {
	const date = toDate(value);
	if (!date) return String(value);
	if (!normalize) return date.toLocaleString();
	const format = new Intl.DateTimeFormat(undefined, {
		timeZone: timezone,
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
	return format.format(date);
}

function parseDateInput(value: string): { year: number; month: number; day: number } | null {
	const match = /^\d{4}-\d{2}-\d{2}$/.exec(value);
	if (!match) return null;
	const [year, month, day] = value.split('-').map((part) => Number(part));
	if (!year || !month || !day) return null;
	return { year, month, day };
}

function parseDateTimeInput(value: string): {
	year: number;
	month: number;
	day: number;
	hour: number;
	minute: number;
} | null {
	const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
	if (!match) return null;
	const year = Number(match[1]);
	const month = Number(match[2]);
	const day = Number(match[3]);
	const hour = Number(match[4]);
	const minute = Number(match[5]);
	if (!year || !month || !day || Number.isNaN(hour) || Number.isNaN(minute)) return null;
	return { year, month, day, hour, minute };
}

function getTimeZoneOffsetMinutes(date: Date, timezone: string): number {
	const format = new Intl.DateTimeFormat('en-CA', {
		timeZone: timezone,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
		hour12: false
	});
	const parts = format.formatToParts(date);
	const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
	const asUtc = Date.UTC(
		Number(map.year),
		Number(map.month) - 1,
		Number(map.day),
		Number(map.hour),
		Number(map.minute),
		Number(map.second)
	);
	return (asUtc - date.getTime()) / 60000;
}

export function toEpoch(value: DateInput, timezone: string, normalize: boolean): number {
	if (value instanceof Date) return value.getTime();
	const input = String(value);
	if (!normalize) return new Date(input).getTime();
	if (hasTimezone(input)) return new Date(input).getTime();
	const parts = parseIsoParts(input);
	if (!parts) return new Date(input).getTime();
	const base = new Date(
		Date.UTC(
			parts.year,
			parts.month - 1,
			parts.day,
			parts.hour,
			parts.minute,
			parts.second,
			parts.millisecond
		)
	);
	const offsetMinutes = getTimeZoneOffsetMinutes(base, timezone);
	return base.getTime() - offsetMinutes * 60000;
}

export function formatDateForInput(value: DateInput, timezone: string, normalize: boolean): string {
	if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
	const date = toDate(value);
	if (!date) return '';
	if (!normalize) return date.toISOString().slice(0, 10);
	const format = new Intl.DateTimeFormat('en-CA', {
		timeZone: timezone,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	});
	const parts = format.formatToParts(date);
	const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
	return `${map.year}-${map.month}-${map.day}`;
}

export function formatDateTimeForInput(
	value: DateInput,
	timezone: string,
	normalize: boolean
): string {
	const date = toDate(value);
	if (!date) return '';
	if (!normalize) return date.toISOString().slice(0, 16);
	const format = new Intl.DateTimeFormat('en-CA', {
		timeZone: timezone,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
	const parts = format.formatToParts(date);
	const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
	return `${map.year}-${map.month}-${map.day}T${map.hour}:${map.minute}`;
}

export function parseDateTimeInputToIso(
	value: string,
	timezone: string,
	normalize: boolean
): string {
	if (!value) return '';
	if (!normalize) return new Date(value).toISOString();
	const parsed = parseDateTimeInput(value);
	if (!parsed) return '';
	const base = new Date(
		Date.UTC(parsed.year, parsed.month - 1, parsed.day, parsed.hour, parsed.minute, 0)
	);
	const offsetMinutes = getTimeZoneOffsetMinutes(base, timezone);
	const utc = new Date(base.getTime() - offsetMinutes * 60000);
	return utc.toISOString();
}

export function getYearInZone(
	value: DateInput,
	timezone: string,
	normalize: boolean
): number | null {
	const date = toDate(value);
	if (!date) return null;
	if (!normalize) return date.getFullYear();
	const format = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric' });
	const year = Number(format.format(date));
	if (Number.isNaN(year)) return date.getFullYear();
	return year;
}
