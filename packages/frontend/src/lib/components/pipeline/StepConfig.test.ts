import { afterEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import StepConfig from './StepConfig.svelte';
import { analysisStore } from '$lib/stores/analysis.svelte';
import type { Analysis } from '$lib/types/analysis';

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

	test('apply stores the filename typed into a download step', async () => {
		const updateStepConfig = vi
			.spyOn(analysisStore, 'updateStepConfig')
			.mockImplementation(() => {});
		render(StepConfig, {
			props: {
				step: {
					id: 'step-download',
					type: 'download',
					config: { format: 'csv', filename: 'hermes_export' },
					depends_on: [],
					is_applied: true
				},
				schema: { columns: [], row_count: null }
			}
		});

		const filename = await screen.findByLabelText('Filename');
		await fireEvent.input(filename, { target: { value: 'renamed_export' } });
		const apply = screen.getByRole('button', { name: 'Apply' });
		expect(apply).toBeEnabled();
		await fireEvent.click(apply);

		expect(updateStepConfig).toHaveBeenCalledWith(
			'step-download',
			expect.objectContaining({ filename: 'renamed_export', format: 'csv' })
		);
		updateStepConfig.mockRestore();
	});

	test('apply stays disabled until a download step has a filename', async () => {
		render(StepConfig, {
			props: {
				step: {
					id: 'step-download',
					type: 'download',
					config: { format: 'csv', filename: '' },
					depends_on: [],
					is_applied: false
				},
				schema: { columns: [], row_count: null }
			}
		});

		const apply = await screen.findByRole('button', { name: 'Apply' });
		expect(apply).toBeDisabled();
		expect(apply).toHaveAttribute('title', 'Enter a filename');
	});

	test('staging a sort column enables Apply', async () => {
		const datasourceId = 'ds-sort';
		analysisStore.current = {
			id: 'analysis-sort',
			name: 'Sort',
			description: null,
			pipeline_definition: {},
			created_at: '',
			updated_at: '',
			revision: 1,
			result_path: null,
			thumbnail: null
		} satisfies Analysis;
		analysisStore.tabs = [
			{
				id: 'tab-sort',
				name: 'Source',
				parent_id: null,
				datasource: { id: datasourceId, analysis_tab_id: null, config: { branch: 'master' } },
				output: {
					result_id: '550e8400-e29b-41d4-a716-446655440000',
					format: 'parquet',
					filename: 'source'
				},
				steps: [
					{
						id: 'step-sort',
						type: 'sort',
						config: {},
						depends_on: [],
						is_applied: true
					}
				]
			}
		];
		analysisStore.activeTabId = 'tab-sort';
		analysisStore.sourceSchemas.set(datasourceId, {
			columns: [
				{ name: 'value', dtype: 'Float64', nullable: true },
				{ name: 'value_mean', dtype: 'Float64', nullable: true }
			],
			row_count: 10
		});
		const updateStepConfig = vi
			.spyOn(analysisStore, 'updateStepConfig')
			.mockImplementation(() => {});

		render(StepConfig, {
			props: {
				step: analysisStore.pipeline[0],
				schema: {
					columns: [
						{ name: 'value', dtype: 'Float64', nullable: true },
						{ name: 'value_mean', dtype: 'Float64', nullable: true }
					],
					row_count: 10
				}
			}
		});

		const apply = await screen.findByRole('button', { name: 'Apply' });
		expect(apply).toBeDisabled();

		await fireEvent.click(screen.getByRole('button', { name: 'Select column...' }));
		await fireEvent.input(screen.getByLabelText('Search'), { target: { value: 'value_mean' } });
		await fireEvent.click(await screen.findByText('value_mean'));
		await fireEvent.click(screen.getByRole('button', { name: 'Add sort rule' }));

		expect(apply).toBeEnabled();
		await fireEvent.click(apply);
		expect(updateStepConfig).toHaveBeenCalledWith(
			'step-sort',
			expect.objectContaining({ columns: ['value_mean'], descending: [false] })
		);
		updateStepConfig.mockRestore();
	});
});

afterEach(() => {
	analysisStore.reset();
});
