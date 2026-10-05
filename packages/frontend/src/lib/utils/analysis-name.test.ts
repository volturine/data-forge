import { describe, expect, test } from 'vitest';
import { nextAnalysisName } from './analysis-name';

describe('nextAnalysisName', () => {
	test('keeps the first name', () => {
		expect(nextAnalysisName('Sensors Analysis', [])).toBe('Sensors Analysis');
	});

	test('adds the next free copy suffix', () => {
		expect(nextAnalysisName('Sensors Analysis', ['Sensors Analysis', 'Sensors Analysis (2)'])).toBe(
			'Sensors Analysis (3)'
		);
	});
});
