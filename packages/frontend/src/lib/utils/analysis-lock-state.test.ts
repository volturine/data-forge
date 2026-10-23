import { describe, expect, test } from 'vitest';
import { getEditorAccessState, isEditorReadOnly } from './analysis-lock-state';

describe('analysis lock state', () => {
	test('maps each editor access state to its access label and read-only flag', () => {
		const cases = [
			// pending access is read-only
			{ access: 'pending', state: 'pending', readOnly: true },
			// owned access is editable
			{ access: 'owned', state: 'editable', readOnly: false },
			// another owner means locked
			{ access: 'other', state: 'locked', readOnly: true },
			// handshake failures are unavailable
			{ access: 'error', state: 'unavailable', readOnly: true },
			// a manually released editor is read-only
			{ access: 'released', state: 'released', readOnly: true }
		] as const;
		for (const { access, state, readOnly } of cases) {
			expect(getEditorAccessState(access)).toBe(state);
			expect(isEditorReadOnly(access)).toBe(readOnly);
		}
	});
});
