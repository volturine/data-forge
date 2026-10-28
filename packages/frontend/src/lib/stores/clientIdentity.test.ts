import { beforeEach, describe, expect, test, vi } from 'vitest';
import type { Fingerprint } from './clientIdentity.svelte';

const { mockIdbGet, mockIdbSet, mockUuid } = vi.hoisted(() => ({
	mockIdbGet: vi.fn(),
	mockIdbSet: vi.fn(),
	mockUuid: vi.fn()
}));

vi.mock('#lib/utils/indexeddb.js', () => ({
	idbGet: (...args: unknown[]) => mockIdbGet(...args),
	idbSet: (...args: unknown[]) => mockIdbSet(...args)
}));

vi.mock('#lib/utils/uuid.js', () => ({ uuid: () => mockUuid() }));
vi.mock('$app/env', () => ({ browser: true, building: false, dev: true, version: 'test' }));

const UUID_A = '00000000-0000-4000-8000-000000000001';
const UUID_B = '00000000-0000-4000-8000-000000000002';

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((resolvePromise) => {
		resolve = resolvePromise;
	});
	return { promise, resolve };
}

const loadClientIdentity = () => import('./clientIdentity.svelte');

beforeEach(() => {
	vi.resetModules();
	vi.clearAllMocks();
	sessionStorage.clear();
	mockIdbGet.mockResolvedValue('stored-client-id');
	mockIdbSet.mockResolvedValue(undefined);
	mockUuid.mockReset();
	mockUuid.mockReturnValue(UUID_A);
});

describe('hashFingerprint', () => {
	test('keeps the hash contract across fingerprint fields and edge inputs', async () => {
		const { hashFingerprint } = await loadClientIdentity();
		const fingerprint: Fingerprint = {
			screen: '1920x1080',
			timezone: 'Europe/Berlin',
			language: 'en-US',
			platform: 'MacIntel'
		};
		const baseline = hashFingerprint(fingerprint);
		expect(baseline).toMatch(/^-?[0-9a-f]+$/);
		expect(hashFingerprint({ ...fingerprint })).toBe(baseline);

		const variants: Array<[string, Fingerprint]> = [
			['screen', { ...fingerprint, screen: '2560x1440' }],
			['timezone', { ...fingerprint, timezone: 'America/New_York' }],
			['language', { ...fingerprint, language: 'de-DE' }],
			['platform', { ...fingerprint, platform: 'Win32' }]
		];
		for (const [field, variant] of variants) {
			expect(hashFingerprint(variant), `changing ${field} changes the fingerprint hash`).not.toBe(
				baseline
			);
		}

		expect(hashFingerprint({ screen: '', timezone: '', language: '', platform: '' })).toMatch(
			/^-?[0-9a-f]+$/
		);
		expect(hashFingerprint({ ...fingerprint, language: '日本語' })).toMatch(/^-?[0-9a-f]+$/);
	});
});

describe('getClientIdentity', () => {
	test('coalesces reads and preserves an existing ID and public identity shape', async () => {
		const read = deferred<string | null>();
		const readStarted = deferred<void>();
		mockIdbGet.mockImplementation((key: unknown) => {
			expect(key).toBe('client_id');
			readStarted.resolve();
			return read.promise;
		});

		try {
			const { getClientIdentity } = await loadClientIdentity();
			await readStarted.promise;
			const initial = [getClientIdentity(), getClientIdentity(), getClientIdentity()] as const;
			expect(initial.map(({ clientId }) => clientId)).toEqual(['', '', '']);
			expect(mockIdbGet).toHaveBeenCalledTimes(1);
			const [first, second, third] = initial;
			expect(first.clientSignature).toMatch(/^-?[0-9a-f]+$/);
			expect(second.clientSignature).toBe(first.clientSignature);
			expect(third.clientSignature).toBe(first.clientSignature);

			read.resolve('persisted-client-id');
			await vi.waitFor(() => expect(getClientIdentity().clientId).toBe('persisted-client-id'));
			expect(mockIdbGet).toHaveBeenCalledTimes(1);
			expect(mockUuid).not.toHaveBeenCalled();
			expect(mockIdbSet).not.toHaveBeenCalled();
		} finally {
			read.resolve('persisted-client-id');
			await read.promise;
		}
	});

	test('generates one ID and keeps it stable through the write commit', async () => {
		const read = deferred<string | null>();
		const readStarted = deferred<void>();
		const writeGate = deferred<void>();
		mockIdbGet.mockImplementation((key: unknown) => {
			expect(key).toBe('client_id');
			readStarted.resolve();
			return read.promise;
		});
		mockIdbSet.mockImplementation((key: unknown) => {
			expect(key).toBe('client_id');
			return writeGate.promise;
		});

		try {
			const { getClientIdentity } = await loadClientIdentity();
			await readStarted.promise;
			expect(getClientIdentity().clientId).toBe('');
			expect(getClientIdentity().clientId).toBe('');
			expect(mockIdbGet).toHaveBeenCalledTimes(1);
			expect(mockIdbSet).not.toHaveBeenCalled();

			read.resolve(null);
			await vi.waitFor(() => expect(mockIdbSet).toHaveBeenCalledTimes(1));
			const generatedId = String(mockIdbSet.mock.calls[0]?.[1]);
			expect(generatedId).toBe(UUID_A);
			expect(getClientIdentity().clientId).toBe(generatedId);
			expect(getClientIdentity().clientId).toBe(generatedId);
			expect(mockIdbGet).toHaveBeenCalledTimes(1);
			expect(mockUuid).toHaveBeenCalledTimes(1);
			expect(mockIdbSet).toHaveBeenCalledTimes(1);

			writeGate.resolve();
			await writeGate.promise;
			expect(getClientIdentity().clientId).toBe(generatedId);
			expect(mockIdbGet).toHaveBeenCalledTimes(1);
			expect(mockUuid).toHaveBeenCalledTimes(1);
			expect(mockIdbSet).toHaveBeenCalledTimes(1);
		} finally {
			read.resolve(null);
			writeGate.resolve();
			await Promise.all([read.promise, writeGate.promise]);
		}
	});
});

describe('getEditorClientId', () => {
	test('persists and reloads one identity for the current tab', async () => {
		mockUuid.mockReset();
		mockUuid.mockReturnValueOnce(UUID_A).mockReturnValueOnce(UUID_B);
		const firstModule = await loadClientIdentity();
		const editorClientId = firstModule.getEditorClientId();

		expect(editorClientId).toBe(UUID_A);
		expect(sessionStorage.getItem('dataforge_editor_client_id')).toBe(UUID_A);
		expect(firstModule.getEditorClientId()).toBe(UUID_A);
		expect(mockUuid).toHaveBeenCalledTimes(1);

		vi.resetModules();
		const reloadedModule = await loadClientIdentity();
		expect(reloadedModule.getEditorClientId()).toBe(UUID_A);
		expect(sessionStorage.getItem('dataforge_editor_client_id')).toBe(UUID_A);
		expect(mockUuid).toHaveBeenCalledTimes(1);
	});
});
