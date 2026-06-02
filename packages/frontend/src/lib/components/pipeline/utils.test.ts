import { describe, expect, test } from 'vitest';

import { getStepTypeConfig } from './utils';

describe('pipeline step summaries', () => {
	test('timeseries add summary prefers the configured period over stale extract component state', () => {
		const summary = getStepTypeConfig('timeseries').summary({
			column: 'event_date',
			operation_type: 'add',
			component: 'year',
			value: 2,
			unit: 'days',
			new_column: 'shifted_date'
		});

		expect(summary).toBe('event_date.add(2 days) → shifted_date');
	});
});
