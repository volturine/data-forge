import {
	getEditorAccessState,
	isEditorReadOnly,
	type EditorLockMode
} from '$lib/utils/analysis-lock-state';
import { openLockSession, type LockSessionError } from '$lib/api/locks';

export type EditorLockControllerDeps = {
	validAnalysisId: () => string | null;
	getDraftLoaded: () => boolean;
	getIsSaving: () => boolean;
	getIsDirty: () => boolean;
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
	const lockedByOther = $derived(lockMode === 'other');
	const lockReadOnly = $derived(lockIntent === 'released' || isEditorReadOnly(lockMode));
	const editorReadOnly = $derived(
		lockReadOnly || !deps.getDraftLoaded() || remoteLockSyncPending || remoteLockSyncFailed
	);
	const saveButtonState = $derived.by(() => {
		if (editorAccessState === 'pending') return 'pending';
		if (editorAccessState === 'locked') return 'locked';
		if (editorAccessState === 'unavailable') return 'readonly';
		if (editorAccessState === 'released') return 'released';
		if (deps.getIsSaving()) return 'saving';
		if (deps.getIsDirty()) return 'dirty';
		return 'clean';
	});
	const saveButtonLabel = $derived.by(() => {
		if (editorAccessState === 'pending') return 'Connecting...';
		if (editorAccessState === 'locked') return 'Locked';
		if (editorAccessState === 'unavailable') return 'Read only';
		if (editorAccessState === 'released') return 'Read only';
		if (deps.getIsSaving()) return 'Saving...';
		if (deps.getIsDirty()) return 'Save';
		return 'Saved';
	});
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

	function handleToggle(): void {
		if (editorAccessState === 'pending' || editorAccessState === 'locked') return;
		lockIntent = lockIntent === 'released' ? 'editing' : 'released';
	}

	function startSessionWatcher(): void {
		// Websocket: $derived can't manage lock acquire + websocket watcher lifecycle.
		$effect(() => {
			const nextId = deps.validAnalysisId();
			if (!nextId) return;
			const id = nextId;
			if (lockIntent === 'released') {
				lockMode = 'released';
				return;
			}

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
					lockMode = ownsLock ? 'owned' : 'other';
				},
				onError(error: LockSessionError) {
					if (!alive) return;
					if (error.statusCode === 409) {
						lockMode = 'other';
						return;
					}
					lockMode = 'error';
				}
			});
			session.acquire();

			return () => {
				alive = false;
				session.close();
				lockMode = lockIntent === 'released' ? 'released' : 'pending';
			};
		});
	}

	return {
		get lockMode() {
			return lockMode;
		},
		get lockIntent() {
			return lockIntent;
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
		get lockedByOther() {
			return lockedByOther;
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
		startSessionWatcher
	};
}

export type EditorLockController = ReturnType<typeof createEditorLockController>;
