export type TemporalInput = string | number | Temporal.Instant;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DATETIME_RE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?$/;
const TIMEZONE_RE = /(?:[zZ]|[+-]\d{2}:?\d{2})$/;
const SECOND_EPOCH_THRESHOLD = 10_000_000_000;

function normalizeIsoText(value: string): string {
	return value.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}.*)$/, '$1T$2');
}

function instantFromDateKey(value: string, timeZone: string): Temporal.Instant {
	return Temporal.PlainDate.from(value)
		.toZonedDateTime({ timeZone, plainTime: '00:00' })
		.toInstant();
}

function instantFromDateTime(value: string, timeZone: string): Temporal.Instant {
	return Temporal.PlainDateTime.from(normalizeIsoText(value)).toZonedDateTime(timeZone).toInstant();
}

export function localTimeZone(): string {
	return Temporal.Now.timeZoneId();
}

export function nowEpochMs(): number {
	return Temporal.Now.instant().epochMilliseconds;
}

export function hasTimezone(value: string): boolean {
	return TIMEZONE_RE.test(value);
}

export function normalizeEpochMilliseconds(value: number): number | null {
	if (!Number.isFinite(value)) return null;
	const epochMs = Math.abs(value) < SECOND_EPOCH_THRESHOLD ? value * 1000 : value;
	return Math.round(epochMs);
}

export function parseInstantWithZone(
	value: TemporalInput,
	timeZone: string,
	normalize: boolean
): Temporal.Instant | null {
	if (value instanceof Temporal.Instant) return value;
	if (typeof value === 'number') {
		const epochMs = normalizeEpochMilliseconds(value);
		return epochMs === null ? null : Temporal.Instant.fromEpochMilliseconds(epochMs);
	}
	const raw = String(value).trim();
	if (!raw) return null;
	try {
		if (hasTimezone(raw)) return Temporal.Instant.from(normalizeIsoText(raw));
		if (DATE_RE.test(raw)) return instantFromDateKey(raw, normalize ? timeZone : 'UTC');
		if (DATETIME_RE.test(raw)) {
			const zone = normalize ? timeZone : localTimeZone();
			return instantFromDateTime(raw, zone);
		}
		return Temporal.Instant.from(normalizeIsoText(raw));
	} catch {
		return null;
	}
}

export function parseInstant(value: TemporalInput): Temporal.Instant | null {
	return parseInstantWithZone(value, localTimeZone(), false);
}

export function parsePlainDateTime(
	value: TemporalInput,
	timeZone: string = localTimeZone()
): Temporal.PlainDateTime | null {
	if (typeof value === 'string') {
		const raw = value.trim();
		if (!raw) return null;
		try {
			if (DATE_RE.test(raw)) return Temporal.PlainDate.from(raw).toPlainDateTime('00:00');
			if (!hasTimezone(raw) && DATETIME_RE.test(raw)) {
				return Temporal.PlainDateTime.from(normalizeIsoText(raw));
			}
		} catch {
			return null;
		}
	}
	const instant = parseInstant(value);
	if (!instant) return null;
	return instant.toZonedDateTimeISO(timeZone).toPlainDateTime();
}

export function parsePlainDate(
	value: TemporalInput,
	timeZone: string = localTimeZone()
): Temporal.PlainDate | null {
	const dateTime = parsePlainDateTime(value, timeZone);
	return dateTime?.toPlainDate() ?? null;
}

export function startOfDayEpoch(dateKey: string, timeZone: string = localTimeZone()): number {
	return instantFromDateKey(dateKey, timeZone).epochMilliseconds;
}

export function endOfDayEpoch(dateKey: string, timeZone: string = localTimeZone()): number {
	return (
		Temporal.PlainDate.from(dateKey)
			.add({ days: 1 })
			.toZonedDateTime({ timeZone, plainTime: '00:00' })
			.toInstant().epochMilliseconds - 1
	);
}

export function localDayKey(
	value: TemporalInput,
	timeZone: string = localTimeZone()
): string | null {
	const date = parsePlainDate(value, timeZone);
	return date?.toString() ?? null;
}

export function isSameLocalDay(left: TemporalInput, right: TemporalInput): boolean {
	const leftKey = localDayKey(left);
	if (!leftKey) return false;
	return leftKey === localDayKey(right);
}

export function isYesterday(value: TemporalInput, now: TemporalInput = nowEpochMs()): boolean {
	const date = parsePlainDate(value);
	const today = parsePlainDate(now);
	if (!date || !today) return false;
	return date.equals(today.subtract({ days: 1 }));
}

export function formatEpoch(
	epochMs: number,
	options: Intl.DateTimeFormatOptions,
	timeZone?: string
): string {
	const normalized = normalizeEpochMilliseconds(epochMs);
	if (normalized === null) return String(epochMs);
	const next = timeZone ? { ...options, timeZone } : options;
	return new Intl.DateTimeFormat(undefined, next).format(normalized);
}

export function formatValue(
	value: TemporalInput,
	options: Intl.DateTimeFormatOptions,
	timeZone?: string
): string {
	const instant = parseInstant(value);
	if (!instant) return String(value);
	return formatEpoch(instant.epochMilliseconds, options, timeZone);
}

export function monthKey(year: number, month: number): string {
	return `${year}-${String(month).padStart(2, '0')}`;
}

export function shiftMonthKey(value: string, delta: number): string {
	return Temporal.PlainYearMonth.from(value).add({ months: delta }).toString();
}

export function monthMeta(
	value: string
): { year: number; month: number; daysInMonth: number; offset: number } | null {
	try {
		const month = Temporal.PlainYearMonth.from(value);
		const first = month.toPlainDate({ day: 1 });
		return {
			year: first.year,
			month: first.month,
			daysInMonth: first.daysInMonth,
			offset: first.dayOfWeek - 1
		};
	} catch {
		return null;
	}
}

export function nowInputParts(): { date: string; month: string; hour: string; minute: string } {
	const now = Temporal.Now.zonedDateTimeISO();
	return {
		date: now.toPlainDate().toString(),
		month: monthKey(now.year, now.month),
		hour: String(now.hour).padStart(2, '0'),
		minute: String(now.minute).padStart(2, '0')
	};
}
