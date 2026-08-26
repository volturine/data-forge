import { describe, expect, test, vi, beforeEach } from 'vitest';
import { flushSync } from 'svelte';
import type { LockSession, LockSessionError, LockStatus } from '$lib/api/locks';

type StatusHandler = (lock: LockStatus | null, ownsLock: boolean) => void;

const acquire = vi.fn();
const close = vi.fn();
let onStatus: StatusHandler | null = null;

vi.mock('$lib/api/locks', () => ({
	openLockSession: vi.fn(
		(options: {
			onStatus: StatusHandler;
			onError?: (error: LockSessionError) => void;
		}): LockSession => {
			onStatus = options.onStatus;
			return {
				acquire,
				release: vi.fn(),
				close
			};
		}
	)
}));

const { createEditorLockController } = await import('./analysis-editor-lock.svelte');
const { createDraftController } = await import('./analysis-editor-draft.svelte');

const ANALYSIS_ID = '11111111-1111-1111-1111-111111111111';

function ownedLock(): LockStatus {
	return {
		resource_type: 'analysis',
		resource_id: ANALYSIS_ID,
		owner_id: 'user-1',
		lock_token: 'token-1',
		acquired_at: '2026-01-01T00:00:00.000Z',
		expires_at: '2026-01-01T00:10:00.000Z',
		last_heartbeat: '2026-01-01T00:00:00.000Z',
		is_expired: false
	};
}

function createEditor(hydrateOnOwned: boolean) {
	const lock = createEditorLockController({
		validAnalysisId: () => ANALYSIS_ID,
		getDraftLoaded: () => draft.draftLoaded,
		getIsSaving: () => false,
		getIsDirty: () => false,
		onOwned: hydrateOnOwned ? () => draft.hydrate() : undefined
	});
	const draft = createDraftController({
		getStorageKey: () => `analysis-draft:${ANALYSIS_ID}`,
		getAnalysisId: () => ANALYSIS_ID,
		blockedFromHydration: () =>
			lock.lockReadOnly || lock.remoteLockSyncPending || lock.remoteLockSyncFailed,
		readOnly: () => lock.editorReadOnly,
		hasTabs: () => true,
		getServerVersion: () => 'v1',
		buildPayload: () => ({
			analysisId: ANALYSIS_ID,
			version: 'v1',
			tabs: [],
			activeTabId: null,
			resourceConfig: null,
			engineDefaults: null,
			selectedStepId: null,
			leftPaneCollapsed: false,
			rightPaneCollapsed: false
		}),
		applyDraft: () => undefined
	});
	return { lock, draft };
}

async function settleHydrate(): Promise<void> {
	await Promise.resolve();
	await Promise.resolve();
	flushSync();
}

describe('analysis editor lock + draft', () => {
	beforeEach(() => {
		acquire.mockClear();
		close.mockClear();
		onStatus = null;
	});

	test('hydrate is a no-op while the lock is still pending', async () => {
		const { lock, draft } = createEditor(true);
		lock.sync(ANALYSIS_ID);
		flushSync();

		expect(lock.editorAccessState).toBe('pending');
		draft.hydrate();
		await settleHydrate();
		expect(draft.draftLoaded).toBe(false);
		expect(lock.editorAccessState).toBe('pending');
	});

	test('stays pending after lock ownership if draft hydrate is not retried', async () => {
		const { lock, draft } = createEditor(false);
		lock.sync(ANALYSIS_ID);
		draft.hydrate();
		await settleHydrate();
		onStatus?.(ownedLock(), true);
		flushSync();

		expect(draft.draftLoaded).toBe(false);
		expect(lock.lockMode).toBe('owned');
		expect(lock.editorAccessState).toBe('pending');
	});

	test('hydrates when the lock is acquired so the editor can become editable', async () => {
		const { lock, draft } = createEditor(true);
		lock.sync(ANALYSIS_ID);
		draft.hydrate();
		await settleHydrate();
		expect(draft.draftLoaded).toBe(false);

		onStatus?.(ownedLock(), true);
		await settleHydrate();

		expect(draft.draftLoaded).toBe(true);
		expect(lock.editorAccessState).toBe('editable');
	});

	test('takeover hydrates after remote snap-back finishes', async () => {
		const { lock, draft } = createEditor(true);
		lock.sync(ANALYSIS_ID);
		onStatus?.(ownedLock(), false);
		lock.setRemoteSyncPending(true);
		draft.hydrate();
		await settleHydrate();
		expect(lock.editorAccessState).toBe('locked');

		onStatus?.(ownedLock(), true);
		await settleHydrate();
		expect(draft.draftLoaded).toBe(false);
		expect(lock.editorAccessState).toBe('pending');

		lock.setRemoteSyncPending(false);
		draft.hydrate();
		await settleHydrate();
		expect(draft.draftLoaded).toBe(true);
		expect(lock.editorAccessState).toBe('editable');
	});
});
