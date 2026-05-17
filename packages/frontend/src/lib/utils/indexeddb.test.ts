import { describe, test, expect, vi, beforeEach } from 'vitest';

vi.mock('$app/environment', () => ({
	browser: false,
	building: false,
	dev: true,
	version: 'test'
}));

const { idbGet, idbSet, idbDelete, idbClear, idbEntries } = await import('./indexeddb');

describe('indexeddb (non-browser)', () => {
	test('idbGet returns null when not in browser', async () => {
		const result = await idbGet('key');
		expect(result).toBeNull();
	});

	test('idbSet does not throw when not in browser', async () => {
		await expect(idbSet('key', 'value')).resolves.toBeUndefined();
	});

	test('idbDelete does not throw when not in browser', async () => {
		await expect(idbDelete('key')).resolves.toBeUndefined();
	});

	test('idbClear does not throw when not in browser', async () => {
		await expect(idbClear()).resolves.toBeUndefined();
	});

	test('idbEntries returns empty array when not in browser', async () => {
		const result = await idbEntries();
		expect(result).toEqual([]);
	});
});

describe('indexeddb (browser without indexedDB)', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	test('idbGet returns null when indexedDB is unavailable', async () => {
		vi.doMock('$app/environment', () => ({
			browser: true,
			building: false,
			dev: true,
			version: 'test'
		}));
		const mod = await import('./indexeddb');
		const result = await mod.idbGet('key');
		expect(result).toBeNull();
	});

	test('idbSet silently fails when indexedDB is unavailable', async () => {
		vi.doMock('$app/environment', () => ({
			browser: true,
			building: false,
			dev: true,
			version: 'test'
		}));
		const mod = await import('./indexeddb');
		await expect(mod.idbSet('key', 'value')).resolves.toBeUndefined();
	});

	test('idbDelete silently fails when indexedDB is unavailable', async () => {
		vi.doMock('$app/environment', () => ({
			browser: true,
			building: false,
			dev: true,
			version: 'test'
		}));
		const mod = await import('./indexeddb');
		await expect(mod.idbDelete('key')).resolves.toBeUndefined();
	});

	test('idbClear silently fails when indexedDB is unavailable', async () => {
		vi.doMock('$app/environment', () => ({
			browser: true,
			building: false,
			dev: true,
			version: 'test'
		}));
		const mod = await import('./indexeddb');
		await expect(mod.idbClear()).resolves.toBeUndefined();
	});

	test('idbEntries returns empty array when indexedDB is unavailable', async () => {
		vi.doMock('$app/environment', () => ({
			browser: true,
			building: false,
			dev: true,
			version: 'test'
		}));
		const mod = await import('./indexeddb');
		const result = await mod.idbEntries();
		expect(result).toEqual([]);
	});
});
