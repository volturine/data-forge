export type EditorLockMode = 'pending' | 'owned' | 'other' | 'error' | 'released';

export type EditorAccessState = 'pending' | 'editable' | 'locked' | 'unavailable' | 'released';

export function getEditorAccessState(mode: EditorLockMode): EditorAccessState {
	if (mode === 'owned') return 'editable';
	if (mode === 'other') return 'locked';
	if (mode === 'error') return 'unavailable';
	if (mode === 'released') return 'released';
	return 'pending';
}

export function isEditorReadOnly(mode: EditorLockMode): boolean {
	return getEditorAccessState(mode) !== 'editable';
}
