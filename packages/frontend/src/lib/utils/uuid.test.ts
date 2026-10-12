import { afterEach, describe, expect, test, vi } from 'vitest';
import { uuid } from './uuid';

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('uuid', () => {
	test('uses crypto.randomUUID when available', () => {
		const expected = '75e3b4ea-7f47-4bd1-b4c4-cf62b75717ca';
		const randomUUID = vi.fn(() => expected);
		vi.stubGlobal('crypto', { randomUUID });

		expect(uuid()).toBe(expected);
		expect(randomUUID).toHaveBeenCalledOnce();
	});

	test('generates a version 4 UUID with crypto.getRandomValues when randomUUID is unavailable', () => {
		const getRandomValues = vi.fn((bytes: Uint8Array) => {
			bytes.set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]);
			return bytes;
		});
		vi.stubGlobal('crypto', { getRandomValues });
		const random = vi.spyOn(Math, 'random');

		expect(uuid()).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f');
		expect(getRandomValues).toHaveBeenCalledOnce();
		expect(getRandomValues.mock.calls[0]?.[0]).toHaveLength(16);
		expect(random).not.toHaveBeenCalled();
	});

	test('throws when cryptographic randomness is unavailable', () => {
		vi.stubGlobal('crypto', undefined);

		expect(uuid).toThrow('Cryptographically secure random values are unavailable');
	});
});
