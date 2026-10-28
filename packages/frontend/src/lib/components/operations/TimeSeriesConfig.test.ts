import { describe, expect, test } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/svelte';
import type { Schema } from '#lib/types/schema.js';
import TimeSeriesConfig from './TimeSeriesConfig.svelte';
import { createConfig } from './TimeSeriesConfig.test-fixtures.svelte.js';

const temporalSchema: Schema = {
	columns: [
		{ name: 'event_date', dtype: 'Date', nullable: false },
		{ name: 'event_datetime', dtype: "Datetime(time_unit='us', time_zone=None)", nullable: false },
		{ name: 'event_time', dtype: 'Time', nullable: false },
		{
			name: 'event_timestamp',
			dtype: "Timestamp(time_unit='ms', time_zone=None)",
			nullable: false
		},
		{ name: 'elapsed', dtype: "Duration(time_unit='us')", nullable: false },
		{ name: 'count', dtype: 'Int64', nullable: false }
	],
	row_count: 1
};

describe('TimeSeriesConfig', () => {
	test('shows the no-date warning for a duration-only schema', () => {
		render(TimeSeriesConfig, {
			props: {
				schema: {
					columns: [{ name: 'elapsed', dtype: "Duration(time_unit='us')", nullable: false }],
					row_count: 1
				},
				config: createConfig('extract')
			}
		});

		expect(screen.getByRole('alert')).toHaveTextContent('No date/time columns detected in schema');
	});

	test('keeps date and time types in both time-series column selectors', async () => {
		render(TimeSeriesConfig, {
			props: { schema: temporalSchema, config: createConfig('diff') }
		});

		expect(screen.queryByRole('alert')).not.toBeInTheDocument();

		const sourceGroup = screen.getByRole('group', { name: 'Source Column' });
		await fireEvent.click(within(sourceGroup).getByRole('button'));
		const sourceOptions = within(screen.getByRole('listbox'))
			.getAllByRole('option')
			.map((option) => option.getAttribute('data-column-option'));
		expect(sourceOptions).toEqual([
			'event_date',
			'event_datetime',
			'event_time',
			'event_timestamp'
		]);

		await fireEvent.click(screen.getByRole('option', { name: 'event_date' }));
		const secondDateGroup = screen.getByRole('group', { name: 'Second Date Column' });
		await fireEvent.click(within(secondDateGroup).getByRole('button'));
		const secondDateOptions = within(screen.getByRole('listbox'))
			.getAllByRole('option')
			.map((option) => option.getAttribute('data-column-option'));
		expect(secondDateOptions).toEqual([
			'event_date',
			'event_datetime',
			'event_time',
			'event_timestamp'
		]);
	});
});
