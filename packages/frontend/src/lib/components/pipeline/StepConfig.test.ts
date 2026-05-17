import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import StepConfig from './StepConfig.svelte';

describe('StepConfig', () => {
	test('renders read-only config when the editor is locked', async () => {
		render(StepConfig, {
			props: {
				step: {
					id: 'step-1',
					type: 'filter',
					config: { column: 'city', operator: 'equals', value: 'Bratislava' },
					depends_on: []
				},
				schema: {
					columns: [{ name: 'city', dtype: 'Utf8', nullable: true }],
					row_count: 1
				},
				readOnly: true
			}
		});

		expect(
			await screen.findByText('This analysis is locked. Step configuration is read-only.')
		).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
		expect(screen.getByText(/"column": "city"/)).toBeInTheDocument();
	});
});
