import { describe, test, expect, vi, beforeEach } from 'vitest';

const mockIdbGet = vi.fn();
const mockIdbSet = vi.fn();
const mockIdbDelete = vi.fn();

vi.mock('$lib/utils/indexeddb', () => ({
	idbGet: (...args: unknown[]) => mockIdbGet(...args),
	idbSet: (...args: unknown[]) => mockIdbSet(...args),
	idbDelete: (...args: unknown[]) => mockIdbDelete(...args)
}));

const mockConfigStore = {
	fetch: vi.fn(),
	config: null as { default_namespace?: string } | null
};

vi.mock('$lib/stores/config.svelte', () => ({
	configStore: mockConfigStore
}));

const {
	initNamespace,
	requireNamespace,
	setNamespace,
	switchNamespace,
	useNamespace,
	isNamespaceReady,
	isNamespaceSwitching
} = await import('./namespace.svelte');

describe('namespace store', () => {
	beforeEach(async () => {
		vi.clearAllMocks();
		mockIdbGet.mockResolvedValue(null);
		mockIdbSet.mockResolvedValue(undefined);
		mockIdbDelete.mockResolvedValue(undefined);
		mockConfigStore.config = null;
		mockConfigStore.fetch.mockResolvedValue(undefined);
		await setNamespace('');
	});

	describe('requireNamespace', () => {
		test('throws before init', () => {
			expect(() => requireNamespace()).toThrow('Namespace not initialized');
		});

		test('returns resolved value after init', async () => {
			mockIdbGet.mockResolvedValue('stored-ns');
			await initNamespace();
			expect(requireNamespace()).toBe('stored-ns');
		});
	});

	describe('isNamespaceReady', () => {
		test('returns false before init', () => {
			expect(isNamespaceReady()).toBe(false);
		});

		test('returns true after initNamespace with stored value', async () => {
			mockIdbGet.mockResolvedValue('stored-ns');
			await initNamespace();
			expect(isNamespaceReady()).toBe(true);
		});

		test('returns true after initNamespace resolving from config', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = { default_namespace: 'config-ns' };
			await initNamespace();
			expect(isNamespaceReady()).toBe(true);
		});

		test('rejects init when config default namespace is missing', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = null;
			await expect(initNamespace()).rejects.toThrow('Default namespace missing from config');
			expect(isNamespaceReady()).toBe(false);
		});

		test('returns true when namespace already set before init', async () => {
			await setNamespace('pre-set');
			await initNamespace();
			expect(isNamespaceReady()).toBe(true);
		});
	});

	describe('initNamespace', () => {
		test('loads stored value from IndexedDB', async () => {
			mockIdbGet.mockResolvedValue('stored-ns');
			await initNamespace();
			expect(mockIdbGet).toHaveBeenCalledWith('namespace');
			expect(requireNamespace()).toBe('stored-ns');
		});

		test('resolves from config when IndexedDB is empty', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = { default_namespace: 'config-ns' };
			await initNamespace();
			expect(mockConfigStore.fetch).toHaveBeenCalled();
			expect(requireNamespace()).toBe('config-ns');
		});

		test('rejects when both IndexedDB and config are empty', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = null;
			await expect(initNamespace()).rejects.toThrow('Default namespace missing from config');
		});

		test('persists resolved namespace to IndexedDB', async () => {
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
			expect(requireNamespace()).toBe('already-set');
		});

		test('concurrent calls share the same promise', async () => {
			let resolveIdb: ((v: string | null) => void) | undefined;
			mockIdbGet.mockReturnValue(
				new Promise<string | null>((r) => {
					resolveIdb = r;
				})
			);

			const p1 = initNamespace();
			const p2 = initNamespace();
			const p3 = initNamespace();

			expect(mockIdbGet).toHaveBeenCalledTimes(1);

			resolveIdb!('concurrent-ns');
			await Promise.all([p1, p2, p3]);

			expect(requireNamespace()).toBe('concurrent-ns');
			expect(isNamespaceReady()).toBe(true);
		});

		test('after init completes, pending is cleared for re-init', async () => {
			mockIdbGet.mockResolvedValue('first');
			await initNamespace();
			expect(requireNamespace()).toBe('first');

			await setNamespace('');
			mockIdbGet.mockResolvedValue('second');
			await initNamespace();
			expect(requireNamespace()).toBe('second');
		});

		test('deletes stale empty-string value from IDB during init', async () => {
			mockIdbGet.mockResolvedValue('');
			mockConfigStore.config = { default_namespace: 'repaired' };
			await initNamespace();
			expect(mockIdbDelete).toHaveBeenCalledWith('namespace');
			expect(requireNamespace()).toBe('repaired');
		});

		test('deletes stale whitespace-only value from IDB during init', async () => {
			mockIdbGet.mockResolvedValue('   ');
			mockConfigStore.config = null;
			await expect(initNamespace()).rejects.toThrow('Default namespace missing from config');
			expect(mockIdbDelete).toHaveBeenCalledWith('namespace');
		});
	});

	describe('refresh persistence', () => {
		test('stored namespace survives simulated refresh', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = { default_namespace: 'prod' };
			await initNamespace();
			expect(requireNamespace()).toBe('prod');

			await setNamespace('custom-ns');
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'custom-ns');

			await setNamespace('');
			mockIdbGet.mockResolvedValue('custom-ns');
			await initNamespace();
			expect(requireNamespace()).toBe('custom-ns');
			expect(isNamespaceReady()).toBe(true);
		});

		test('stored value takes precedence over config default', async () => {
			mockIdbGet.mockResolvedValue('stored-production');
			mockConfigStore.config = { default_namespace: 'staging' };
			await initNamespace();
			expect(requireNamespace()).toBe('stored-production');
			expect(mockConfigStore.fetch).not.toHaveBeenCalled();
		});

		test('idbSet is awaited during init', async () => {
			mockIdbGet.mockResolvedValue(null);
			mockConfigStore.config = { default_namespace: 'awaited-ns' };
			await initNamespace();
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'awaited-ns');
		});
	});

	describe('setNamespace', () => {
		test('updates value and persists to IndexedDB', async () => {
			await setNamespace('new-ns');
			expect(requireNamespace()).toBe('new-ns');
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'new-ns');
		});

		test('overwrites previously set value', async () => {
			await setNamespace('first');
			await setNamespace('second');
			expect(requireNamespace()).toBe('second');
		});

		test('empty string resets state and deletes from IDB', async () => {
			await setNamespace('something');
			await setNamespace('');
			expect(isNamespaceReady()).toBe(false);
			expect(mockIdbDelete).toHaveBeenCalledWith('namespace');
		});

		test('whitespace-only string resets state and deletes from IDB', async () => {
			await setNamespace('something');
			await setNamespace('   ');
			expect(isNamespaceReady()).toBe(false);
			expect(mockIdbDelete).toHaveBeenCalledWith('namespace');
		});

		test('marks ready after setting valid value', async () => {
			expect(isNamespaceReady()).toBe(false);
			await setNamespace('direct');
			expect(isNamespaceReady()).toBe(true);
			expect(requireNamespace()).toBe('direct');
		});
	});

	describe('useNamespace', () => {
		test('value getter returns resolved namespace after init', async () => {
			mockIdbGet.mockResolvedValue('ns-1');
			await initNamespace();
			const ns = useNamespace();
			expect(ns.value).toBe('ns-1');
		});

		test('value getter throws before init', () => {
			const ns = useNamespace();
			expect(() => ns.value).toThrow('Namespace not initialized');
		});

		test('ready getter reflects namespace readiness', async () => {
			const ns = useNamespace();
			expect(ns.ready).toBe(false);
			mockIdbGet.mockResolvedValue('ns-1');
			await initNamespace();
			expect(ns.ready).toBe(true);
		});

		test('set method persists to IndexedDB', async () => {
			const ns = useNamespace();
			await ns.set('hook-ns');
			expect(requireNamespace()).toBe('hook-ns');
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'hook-ns');
		});

		test('switching getter reflects namespace switch state', async () => {
			const ns = useNamespace();
			expect(ns.switching).toBe(false);
			let switchingDuring = false;
			await setNamespace('pre');
			await switchNamespace('during', {
				beforeCommit() {
					switchingDuring = ns.switching;
				}
			});
			expect(switchingDuring).toBe(true);
			expect(ns.switching).toBe(false);
		});
	});

	describe('switchNamespace', () => {
		test('calls beforeCommit hook', async () => {
			const beforeCommit = vi.fn();
			await switchNamespace('new-ns', { beforeCommit });
			expect(beforeCommit).toHaveBeenCalledOnce();
		});

		test('sets namespace value', async () => {
			await switchNamespace('switched-ns');
			expect(requireNamespace()).toBe('switched-ns');
			expect(isNamespaceReady()).toBe(true);
			expect(mockIdbSet).toHaveBeenCalledWith('namespace', 'switched-ns');
		});

		test('calls beforeCommit before persisting namespace', async () => {
			const order: string[] = [];
			const beforeCommit = vi.fn(() => {
				order.push('beforeCommit');
			});
			mockIdbSet.mockImplementation(() => {
				order.push('idbSet');
				return Promise.resolve();
			});

			await switchNamespace('ordered-ns', { beforeCommit });
			expect(order.indexOf('beforeCommit')).toBeLessThan(order.indexOf('idbSet'));
		});

		test('calls afterCommit after persisting namespace', async () => {
			const order: string[] = [];
			mockIdbSet.mockImplementation(() => {
				order.push('idbSet');
				return Promise.resolve();
			});
			const afterCommit = vi.fn(() => {
				order.push('afterCommit');
			});

			await switchNamespace('after-ns', { afterCommit });
			expect(order.indexOf('idbSet')).toBeLessThan(order.indexOf('afterCommit'));
		});

		test('works without hooks', async () => {
			await switchNamespace('no-callback');
			expect(requireNamespace()).toBe('no-callback');
		});

		test('sets switching flag during switch', async () => {
			let switchingDuringBeforeCommit = false;
			let switchingDuringAfterCommit = false;
			await switchNamespace('flag-ns', {
				beforeCommit() {
					switchingDuringBeforeCommit = isNamespaceSwitching();
				},
				afterCommit() {
					switchingDuringAfterCommit = isNamespaceSwitching();
				}
			});
			expect(switchingDuringBeforeCommit).toBe(true);
			expect(switchingDuringAfterCommit).toBe(true);
			expect(isNamespaceSwitching()).toBe(false);
		});

		test('clears switching flag even on error', async () => {
			await expect(
				switchNamespace('err-ns', {
					beforeCommit() {
						throw new Error('hook error');
					}
				})
			).rejects.toThrow('hook error');
			expect(isNamespaceSwitching()).toBe(false);
		});
	});
});
