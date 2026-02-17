import { describe, expect, it } from 'vitest';
import {
	formatDateForInput,
	formatDateTimeForInput,
	parseDateTimeInputToIso
} from '$lib/utils/datetime';

describe('datetime utils', () => {
	it('formatDateForInput returns YYYY-MM-DD', () => {
		const result = formatDateForInput('2024-01-02T03:04:05Z', 'UTC', true);
		expect(result).toBe('2024-01-02');
	});

	it('formatDateTimeForInput returns local datetime', () => {
		const result = formatDateTimeForInput('2024-01-02T03:04:05Z', 'UTC', true);
		expect(result).toContain('2024-01-02');
	});

	it('parseDateTimeInputToIso returns ISO string', () => {
		const result = parseDateTimeInputToIso('2024-01-02T03:04', 'UTC', true);
		expect(result).toContain('2024-01-02');
	});
});
