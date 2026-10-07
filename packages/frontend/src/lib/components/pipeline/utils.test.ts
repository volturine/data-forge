import { describe, expect, test } from 'vitest';

import { getStepTypeConfig } from './utils';

describe('pipeline step summaries', () => {
	test('pivot summary lists multiple value columns', () => {
		const summary = getStepTypeConfig('pivot').summary({
			index: ['account'],
			columns: 'quarter',
			value_columns: ['sales', 'units'],
			aggregate_function: 'sum'
		});

		expect(summary).toBe('quarter → sum(sales, units), index: account');
	});

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
