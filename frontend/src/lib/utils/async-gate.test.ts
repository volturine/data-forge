import { describe, expect, test } from 'vitest';
import { createAsyncGate } from './async-gate';

describe('createAsyncGate', () => {
	test('accepts only the latest issued token', () => {
		const gate = createAsyncGate();
		const first = gate.issue();
		const second = gate.issue();

		expect(gate.isCurrent(first)).toBe(false);
		expect(gate.isCurrent(second)).toBe(true);
	});

	test('invalidate expires the current token', () => {
		const gate = createAsyncGate();
		const token = gate.issue();

		gate.invalidate();

		expect(gate.isCurrent(token)).toBe(false);
	});
});
