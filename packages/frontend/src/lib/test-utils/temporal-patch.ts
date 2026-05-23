function parts(
	epochMs: number,
	timeZone: string
): {
	year: number;
	month: number;
	day: number;
	hour: number;
	minute: number;
	second: number;
} {
	const fmt = new Intl.DateTimeFormat('en-CA', {
		timeZone,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
		hour12: false
	});
	const raw: Record<string, string> = {};
	for (const item of fmt.formatToParts(new Date(epochMs))) {
		raw[item.type] = item.value;
	}
	if (raw.hour === '24') raw.hour = '00';
	return {
		year: Number(raw.year),
		month: Number(raw.month),
		day: Number(raw.day),
		hour: Number(raw.hour),
		minute: Number(raw.minute),
		second: Number(raw.second)
	};
}

function offset(epochMs: number, timeZone: string): number {
	const zoned = parts(epochMs, timeZone);
	const utc = Date.UTC(
		zoned.year,
		zoned.month - 1,
		zoned.day,
		zoned.hour,
		zoned.minute,
		zoned.second
	);
	return (utc - epochMs) / 60000;
}

function clock(
	value: string | Temporal.PlainTime | { hour?: number; minute?: number; second?: number }
) {
	if (typeof value === 'string') {
		const match = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
		if (!match) return { hour: 0, minute: 0, second: 0 };
		return {
			hour: Number(match[1]),
			minute: Number(match[2]),
			second: Number(match[3] ?? 0)
		};
	}
	if (value instanceof Temporal.PlainTime) {
		return { hour: value.hour, minute: value.minute, second: value.second };
	}
	return {
		hour: value.hour ?? 0,
		minute: value.minute ?? 0,
		second: value.second ?? 0
	};
}

function instantFromPlain(dateTime: Temporal.PlainDateTime, timeZone: string): Temporal.Instant {
	const base = Date.UTC(
		dateTime.year,
		dateTime.month - 1,
		dateTime.day,
		dateTime.hour,
		dateTime.minute,
		dateTime.second,
		dateTime.millisecond
	);
	return Temporal.Instant.fromEpochMilliseconds(base - offset(base, timeZone) * 60000);
}

class ZonedDateTimeLike {
	instant: Temporal.Instant;
	timeZoneId: string;
	year: number;
	month: number;
	day: number;
	hour: number;
	minute: number;
	second: number;

	constructor(instant: Temporal.Instant, timeZone: string) {
		const value = parts(instant.epochMilliseconds, timeZone);
		this.instant = instant;
		this.timeZoneId = timeZone;
		this.year = value.year;
		this.month = value.month;
		this.day = value.day;
		this.hour = value.hour;
		this.minute = value.minute;
		this.second = value.second;
	}

	toInstant(): Temporal.Instant {
		return this.instant;
	}

	toPlainDate(): Temporal.PlainDate {
		return Temporal.PlainDate.from({ year: this.year, month: this.month, day: this.day });
	}

	toPlainDateTime(): Temporal.PlainDateTime {
		return Temporal.PlainDateTime.from({
			year: this.year,
			month: this.month,
			day: this.day,
			hour: this.hour,
			minute: this.minute,
			second: this.second
		});
	}
}

function define(obj: object, key: string, value: (this: never, ...args: never[]) => unknown) {
	Object.defineProperty(obj, key, {
		configurable: true,
		writable: true,
		value
	});
}

export function patchTemporalForBun(): void {
	if (!('Temporal' in globalThis)) return;

	if (!('toZonedDateTimeISO' in Temporal.Instant.prototype)) {
		define(
			Temporal.Instant.prototype,
			'toZonedDateTimeISO',
			function (this: Temporal.Instant, timeZone: string) {
				return new ZonedDateTimeLike(this, timeZone);
			}
		);
	}

	if (!('toZonedDateTime' in Temporal.PlainDateTime.prototype)) {
		define(
			Temporal.PlainDateTime.prototype,
			'toZonedDateTime',
			function (this: Temporal.PlainDateTime, timeZone: string) {
				return new ZonedDateTimeLike(instantFromPlain(this, timeZone), timeZone);
			}
		);
	}

	if (!('toZonedDateTime' in Temporal.PlainDate.prototype)) {
		define(
			Temporal.PlainDate.prototype,
			'toZonedDateTime',
			function (
				this: Temporal.PlainDate,
				input: {
					timeZone: string;
					plainTime:
						| string
						| Temporal.PlainTime
						| { hour?: number; minute?: number; second?: number };
				}
			) {
				const time = clock(input.plainTime);
				const dateTime = Temporal.PlainDateTime.from({
					year: this.year,
					month: this.month,
					day: this.day,
					hour: time.hour,
					minute: time.minute,
					second: time.second
				});
				return new ZonedDateTimeLike(instantFromPlain(dateTime, input.timeZone), input.timeZone);
			}
		);
	}

	define(Temporal.Now, 'instant', function () {
		return Temporal.Instant.fromEpochMilliseconds(Date.now());
	});

	if (!('zonedDateTimeISO' in Temporal.Now)) {
		define(Temporal.Now, 'zonedDateTimeISO', function () {
			return new ZonedDateTimeLike(Temporal.Now.instant(), Temporal.Now.timeZoneId());
		});
	}

	if (!('plainDateISO' in Temporal.Now)) {
		define(Temporal.Now, 'plainDateISO', function () {
			return new ZonedDateTimeLike(Temporal.Now.instant(), Temporal.Now.timeZoneId()).toPlainDate();
		});
	}
}
