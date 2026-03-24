import { describe, test, expect, vi, beforeEach } from 'vitest';

const mockIdbGet = vi.fn();
const mockIdbSet = vi.fn();

vi.mock('$lib/utils/indexeddb', () => ({
	idbGet: (...args: unknown[]) => mockIdbGet(...args),
	idbSet: (...args: unknown[]) => mockIdbSet(...args)
}));

const mockConfigStore = {
	fetch: vi.fn(),
	config: null as { default_namespace?: string } | null
};

vi.mock('$lib/stores/config.svelte', () => ({
	configStore: mockConfigStore
}));

const { initNamespace, getNamespace, setNamespace, useNamespace } =
	await import('./namespace.svelte');

describe('namespace store', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		mockIdbGet.mockResolvedValue(null);
		mockIdbSet.mockResolvedValue(undefined);
		mockConfigStore.config = null;
		mockConfigStore.fetch.mockResolvedValue(undefined);
		// Reset module-level namespace state so initNamespace doesn't early-return
		await setNamespace('');
	});

	describe('getNamespace', () => {
		test('returns "default" when nothing is set', () => {
			expect(getNamespace()).toBe('default');
		});

		test('returns config default_namespace when available', () => {
			mockConfigStore.config = { default_namespace: 'production' };
			expect(getNamespace()).toBe('production');
		});
	});

	describe('initNamespace', () => {
		test('loads stored value from IndexedDB', async () => {
			mockIdbGet.mockResolvedValue('stored-ns');
			await initNamespace();
			expect(mockIdbGet).toHaveBeenCalledWith('namespace');
			expect(getNamespace()).toBe('stored-ns');
		});

		test('falls back to config default_namespace when IndexedDB is empty', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = { default_namespace: 'config-ns' };
			await initNamespace();
			expect(mockConfigStore.fetch).toHaveBeenCalled();
			expect(getNamespace()).toBe('config-ns');
		});

		test('falls back to "default" when both IndexedDB and config are empty', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = null;
			await initNamespace();
			expect(getNamespace()).toBe('default');
		});

		test('persists config default to IndexedDB', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = { default_namespace: 'persisted' };
			await initNamespace();
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'persisted');
		});

		test('skips fetch when namespace already set', async () => {
			await setNamespace('already-set');
			vi.clearAllMocks();
			await initNamespace();
			expect(mockIdbGet).not.toHaveBeenCalled();
			expect(getNamespace()).toBe('already-set');
		});
	});

	describe('setNamespace', () => {
		test('updates value and persists to IndexedDB', async () => {
			await setNamespace('new-ns');
			expect(getNamespace()).toBe('new-ns');
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'new-ns');
		});

		test('overwrites previously set value', async () => {
			await setNamespace('first');
			await setNamespace('second');
			expect(getNamespace()).toBe('second');
		});
	});

	describe('useNamespace', () => {
		test('value getter returns current namespace', () => {
			const ns = useNamespace();
			expect(ns.value).toBe(getNamespace());
		});

		test('set method persists to IndexedDB', async () => {
			const ns = useNamespace();
			await ns.set('hook-ns');
			expect(getNamespace()).toBe('hook-ns');
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'hook-ns');
		});
	});
});
