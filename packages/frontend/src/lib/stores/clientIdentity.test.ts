import { describe, test, expect, vi, beforeEach } from 'vitest';

const mockIdbGet = vi.fn();
const mockIdbSet = vi.fn();

vi.mock('$lib/utils/indexeddb', () => ({
	idbGet: (...args: unknown[]) => mockIdbGet(...args),
	idbSet: (...args: unknown[]) => mockIdbSet(...args)
}));

const { hashFingerprint, getClientIdentity } = await import('./clientIdentity.svelte');
import type { Fingerprint } from './clientIdentity.svelte';

describe('hashFingerprint', () => {
	const fp: Fingerprint = {
		screen: '1920x1080',
		timezone: 'Europe/Berlin',
		language: 'en-US',
		platform: 'MacIntel'
	};

	test('returns a hex string', () => {
		const hash = hashFingerprint(fp);
		expect(hash).toMatch(/^-?[0-9a-f]+$/);
	});

	test('is deterministic for same input', () => {
		expect(hashFingerprint(fp)).toBe(hashFingerprint(fp));
	});

	test('differs for different screen sizes', () => {
		const other: Fingerprint = { ...fp, screen: '2560x1440' };
		expect(hashFingerprint(fp)).not.toBe(hashFingerprint(other));
	});

	test('differs for different timezones', () => {
		const other: Fingerprint = { ...fp, timezone: 'America/New_York' };
		expect(hashFingerprint(fp)).not.toBe(hashFingerprint(other));
	});

	test('differs for different languages', () => {
		const other: Fingerprint = { ...fp, language: 'de-DE' };
		expect(hashFingerprint(fp)).not.toBe(hashFingerprint(other));
	});

	test('differs for different platforms', () => {
		const other: Fingerprint = { ...fp, platform: 'Win32' };
		expect(hashFingerprint(fp)).not.toBe(hashFingerprint(other));
	});

	test('handles empty fields', () => {
		const empty: Fingerprint = { screen: '', timezone: '', language: '', platform: '' };
		const hash = hashFingerprint(empty);
		expect(hash).toMatch(/^-?[0-9a-f]+$/);
	});

	test('handles unicode in fields', () => {
		const unicode: Fingerprint = { ...fp, language: '日本語' };
		const hash = hashFingerprint(unicode);
		expect(hash).toMatch(/^-?[0-9a-f]+$/);
	});
});

describe('getClientIdentity', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockIdbGet.mockResolvedValue(null);
		mockIdbSet.mockResolvedValue(undefined);
	});

	test('returns an object with clientId and clientSignature', () => {
		const identity = getClientIdentity();
		expect(identity).toHaveProperty('clientId');
		expect(identity).toHaveProperty('clientSignature');
		expect(typeof identity.clientId).toBe('string');
		expect(typeof identity.clientSignature).toBe('string');
	});

	test('clientSignature is a hex hash string', () => {
		const identity = getClientIdentity();
		expect(identity.clientSignature).toMatch(/^-?[0-9a-f]+$/);
	});

	test('returns consistent signature across calls', () => {
		const a = getClientIdentity();
		const b = getClientIdentity();
		expect(a.clientSignature).toBe(b.clientSignature);
	});
});
