import { describe, expect, test } from 'vitest';
import { getEditorAccessState, isEditorReadOnly } from './analysis-lock-state';

describe('analysis lock state', () => {
	test('treats pending access as read-only', () => {
		expect(getEditorAccessState('pending')).toBe('pending');
		expect(isEditorReadOnly('pending')).toBe(true);
	});

	test('treats owned access as editable', () => {
		expect(getEditorAccessState('owned')).toBe('editable');
		expect(isEditorReadOnly('owned')).toBe(false);
	});

	test('treats another owner as locked', () => {
		expect(getEditorAccessState('other')).toBe('locked');
		expect(isEditorReadOnly('other')).toBe(true);
	});

	test('treats handshake failures as unavailable', () => {
		expect(getEditorAccessState('error')).toBe('unavailable');
		expect(isEditorReadOnly('error')).toBe(true);
	});

	test('treats a manually released editor as read-only', () => {
		expect(getEditorAccessState('released')).toBe('released');
		expect(isEditorReadOnly('released')).toBe(true);
	});
});
