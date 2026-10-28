import {
	getEditorAccessState,
	isEditorReadOnly,
	type EditorLockMode
} from '#lib/utils/analysis-lock-state.js';
import { openLockSession, type LockSessionError } from '#lib/api/locks.js';

export type SaveButtonState =
	'pending' | 'locked' | 'readonly' | 'released' | 'saving' | 'dirty' | 'clean';

const SAVE_LABELS = {
	pending: 'Connecting...',
	locked: 'Locked',
	readonly: 'Read only',
	released: 'Read only',
	saving: 'Saving...',
	dirty: 'Save',
	clean: 'Saved'
} satisfies Record<SaveButtonState, string>;

export type EditorLockControllerDeps = {
	validAnalysisId: () => string | null;
	getDraftLoaded: () => boolean;
	getIsSaving: () => boolean;
	getIsDirty: () => boolean;
	onOwned?: () => void;
	onLockedByOther?: () => void;
};

export function createEditorLockController(deps: EditorLockControllerDeps) {
	let lockMode = $state<EditorLockMode>('pending');
	let lockIntent = $state<'editing' | 'released'>('editing');
	let remoteLockSyncPending = $state(false);
	let remoteLockSyncFailed = $state(false);

	const editorAccessState = $derived.by(() => {
		if (lockIntent === 'released') return getEditorAccessState('released');
		if (remoteLockSyncFailed) return getEditorAccessState('error');
		if (lockMode === 'owned' && (!deps.getDraftLoaded() || remoteLockSyncPending)) {
			return getEditorAccessState('pending');
		}
		return getEditorAccessState(lockMode);
	});
	const lockReadOnly = $derived(lockIntent === 'released' || isEditorReadOnly(lockMode));
	const editorReadOnly = $derived(
		lockReadOnly || !deps.getDraftLoaded() || remoteLockSyncPending || remoteLockSyncFailed
	);
	const saveButtonState = $derived.by((): SaveButtonState => {
		if (editorAccessState === 'pending') return 'pending';
		if (editorAccessState === 'locked') return 'locked';
		if (editorAccessState === 'unavailable') return 'readonly';
		if (editorAccessState === 'released') return 'released';
		if (deps.getIsSaving()) return 'saving';
		if (deps.getIsDirty()) return 'dirty';
		return 'clean';
	});
	const saveButtonLabel = $derived(SAVE_LABELS[saveButtonState]);
	const lockButtonLabel = $derived.by(() => {
		if (editorAccessState === 'editable') return 'Unlock';
		if (editorAccessState === 'released') return 'Lock';
		if (editorAccessState === 'locked') return 'Locked';
		if (editorAccessState === 'pending') return 'Locking...';
		return 'Retry lock';
	});
	const lockButtonDisabled = $derived(
		editorAccessState === 'pending' || editorAccessState === 'locked'
	);

	let sessionCleanup: (() => void) | null = null;
	let sessionResourceId: string | null = null;

	function closeSession(): void {
		sessionCleanup?.();
		sessionCleanup = null;
		sessionResourceId = null;
	}

	function openSession(id: string): void {
		closeSession();
		lockMode = 'pending';
		let alive = true;
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: id,
			onStatus(lock, ownsLock) {
				if (!alive) return;
				if (lock === null) {
					lockMode = 'pending';
					session.acquire();
					return;
				}
				const next = ownsLock ? 'owned' : 'other';
				const becameOwned = next === 'owned' && lockMode !== 'owned';
				const becameOther = next === 'other' && lockMode !== 'other';
				lockMode = next;
				if (becameOwned) deps.onOwned?.();
				if (becameOther) deps.onLockedByOther?.();
			},
			onError(error: LockSessionError) {
				if (!alive) return;
				if (error.statusCode === 409) {
					const becameOther = lockMode !== 'other';
					lockMode = 'other';
					if (becameOther) deps.onLockedByOther?.();
					return;
				}
				lockMode = 'error';
			}
		});
		session.acquire();
		sessionResourceId = id;
		sessionCleanup = () => {
			alive = false;
			session.close();
			lockMode = lockIntent === 'released' ? 'released' : 'pending';
		};
	}

	function sync(id: string | null): void {
		if (!id) {
			closeSession();
			return;
		}
		if (lockIntent === 'released') {
			closeSession();
			lockMode = 'released';
			return;
		}
		// Re-syncing the same resource must not tear down a live session; the
		// editor calls sync on every mount and navigation to the same analysis.
		if (sessionResourceId === id) return;
		openSession(id);
	}

	function handleToggle(): void {
		if (editorAccessState === 'pending' || editorAccessState === 'locked') return;
		lockIntent = lockIntent === 'released' ? 'editing' : 'released';
		sync(deps.validAnalysisId());
	}

	function stop(): void {
		closeSession();
	}

	return {
		get lockMode() {
			return lockMode;
		},
		get remoteLockSyncPending() {
			return remoteLockSyncPending;
		},
		get remoteLockSyncFailed() {
			return remoteLockSyncFailed;
		},
		setRemoteSyncPending(value: boolean) {
			remoteLockSyncPending = value;
		},
		setRemoteSyncFailed(value: boolean) {
			remoteLockSyncFailed = value;
		},
		get editorAccessState() {
			return editorAccessState;
		},
		get editorReadOnly() {
			return editorReadOnly;
		},
		get lockReadOnly() {
			return lockReadOnly;
		},
		get saveButtonState() {
			return saveButtonState;
		},
		get saveButtonLabel() {
			return saveButtonLabel;
		},
		get lockButtonLabel() {
			return lockButtonLabel;
		},
		get lockButtonDisabled() {
			return lockButtonDisabled;
		},
		handleToggle,
		sync,
		stop
	};
}
