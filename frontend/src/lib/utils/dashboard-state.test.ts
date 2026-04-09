import { describe, expect, it } from 'vitest';

import type { AnalysisVariableDefinition } from '$lib/types/analysis';
import {
	getAffectedWidgetIds,
	parseDashboardVariableState,
	serializeDashboardVariableState
} from '$lib/utils/dashboard-state';

const variables: AnalysisVariableDefinition[] = [
	{
		id: 'region',
		label: 'Region',
		type: 'single_select',
		default_value: 'emea',
		required: true,
		options: [
			{ label: 'EMEA', value: 'emea' },
			{ label: 'AMER', value: 'amer' }
		],
		option_source: null
	},
	{
		id: 'enabled',
		label: 'Enabled',
		type: 'boolean',
		default_value: false,
		required: true,
		options: [],
		option_source: null
	},
	{
		id: 'range',
		label: 'Range',
		type: 'date_range',
		default_value: { start: '2024-01-01', end: '2024-01-31' },
		required: true,
		options: [],
		option_source: null
	},
	{
		id: 'channels',
		label: 'Channels',
		type: 'multi_select',
		default_value: ['web'],
		required: true,
		options: [
			{ label: 'Web', value: 'web' },
			{ label: 'Retail', value: 'retail' }
		],
		option_source: null
	}
];

describe('dashboard-state', () => {
	it('round-trips variable state through URL params', () => {
		const params = serializeDashboardVariableState(variables, {
			region: 'amer',
			enabled: true,
			range: { start: '2024-02-01', end: '2024-02-15' },
			channels: ['web', 'retail']
		});

		const parsed = parseDashboardVariableState(variables, params);

		expect(parsed).toEqual({
			region: 'amer',
			enabled: true,
			range: { start: '2024-02-01', end: '2024-02-15' },
			channels: ['web', 'retail']
		});
	});

	it('falls back to defaults when params are missing', () => {
		expect(parseDashboardVariableState(variables, new URLSearchParams())).toEqual({
			region: 'emea',
			enabled: false,
			range: { start: '2024-01-01', end: '2024-01-31' },
			channels: ['web']
		});
	});

	it('returns only widgets affected by a variable change', () => {
		expect(
			getAffectedWidgetIds(
				{
					table: ['region'],
					chart: ['region', 'channels'],
					header: []
				},
				'channels'
			)
		).toEqual(['chart']);
	});
});
