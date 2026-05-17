import { describe, test, expect } from 'vitest';
import { formatBytes } from './compression';

describe('formatBytes', () => {
	test('returns 0 B for zero', () => {
		expect(formatBytes(0)).toBe('0 B');
	});

	test('formats bytes below 1 KB', () => {
		expect(formatBytes(1)).toBe('1 B');
		expect(formatBytes(512)).toBe('512 B');
		expect(formatBytes(1023)).toBe('1023 B');
	});

	test('formats kilobytes', () => {
		expect(formatBytes(1024)).toBe('1 KB');
		expect(formatBytes(1536)).toBe('1.5 KB');
		expect(formatBytes(1048575)).toBe('1024 KB');
	});

	test('formats megabytes', () => {
		expect(formatBytes(1048576)).toBe('1 MB');
		expect(formatBytes(1572864)).toBe('1.5 MB');
	});

	test('formats gigabytes', () => {
		expect(formatBytes(1073741824)).toBe('1 GB');
		expect(formatBytes(1610612736)).toBe('1.5 GB');
	});

	test('formats terabytes', () => {
		expect(formatBytes(1099511627776)).toBe('1 TB');
	});

	test('formats petabytes', () => {
		expect(formatBytes(1125899906842624)).toBe('1 PB');
	});

	test('clamps index for values beyond petabytes', () => {
		const exabyte = 1125899906842624 * 1024;
		const result = formatBytes(exabyte);
		expect(result).toContain('PB');
		expect(result).not.toContain('undefined');
	});

	test('returns 0 B for negative numbers', () => {
		expect(formatBytes(-1)).toBe('0 B');
		expect(formatBytes(-1024)).toBe('0 B');
	});

	test('returns 0 B for NaN', () => {
		expect(formatBytes(NaN)).toBe('0 B');
	});

	test('returns 0 B for Infinity', () => {
		expect(formatBytes(Infinity)).toBe('0 B');
		expect(formatBytes(-Infinity)).toBe('0 B');
	});

	test('truncates to two decimal places', () => {
		expect(formatBytes(1234)).toBe('1.21 KB');
		expect(formatBytes(123456789)).toBe('117.74 MB');
	});

	test('drops trailing zeros', () => {
		expect(formatBytes(2048)).toBe('2 KB');
		expect(formatBytes(2560)).toBe('2.5 KB');
	});
});
