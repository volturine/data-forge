import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SelectConfig from './SelectConfig.svelte';
import type { Schema } from '$lib/types/schema';

// TODO: Re-enable when @testing-library/svelte fully supports Svelte 5's mount() API
describe.skip('SelectConfig', () => {
	const mockSchema: Schema = {
		columns: [
			{ name: 'id', dtype: 'Int64', nullable: false },
			{ name: 'name', dtype: 'String', nullable: true },
			{ name: 'age', dtype: 'Int32', nullable: false },
			{ name: 'email', dtype: 'String', nullable: true }
		],
		row_count: 100
	};

	const emptyConfig = {
		columns: []
	};

	const partialConfig = {
		columns: ['id', 'name']
	};

	const fullConfig = {
		columns: ['id', 'name', 'age', 'email']
	};

	describe('rendering', () => {
		it('should render with empty selection', () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			expect(screen.getByText('Select Columns')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: /select all/i })).toBeInTheDocument();
			expect(screen.getByRole('button', { name: /deselect all/i })).toBeInTheDocument();
		});

		it('should render all columns from schema', () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			expect(screen.getByText('id')).toBeInTheDocument();
			expect(screen.getByText('name')).toBeInTheDocument();
			expect(screen.getByText('age')).toBeInTheDocument();
			expect(screen.getByText('email')).toBeInTheDocument();
		});

		it('should display column types', () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			expect(screen.getByText('(Int64)')).toBeInTheDocument();
			expect(screen.getAllByText('(String)')).toHaveLength(2);
			expect(screen.getByText('(Int32)')).toBeInTheDocument();
		});

		it('should pre-select columns from config', () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: partialConfig
				}
			});

			const checkboxes = screen.getAllByRole('checkbox');
			expect(checkboxes[0]).toBeChecked(); // id
			expect(checkboxes[1]).toBeChecked(); // name
			expect(checkboxes[2]).not.toBeChecked(); // age
			expect(checkboxes[3]).not.toBeChecked(); // email
		});

		it('should display selected summary when columns are selected', () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: partialConfig
				}
			});

			expect(screen.getByText(/selected \(2\)/i)).toBeInTheDocument();
			expect(screen.getByText(/id, name/i)).toBeInTheDocument();
		});

		it('should not display summary when no columns are selected', () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			expect(screen.queryByText(/selected/i)).not.toBeInTheDocument();
		});
	});

	describe('column selection/deselection', () => {
		it('should select a column when checkbox is clicked', async () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			const checkboxes = screen.getAllByRole('checkbox');
			await fireEvent.click(checkboxes[0]); // Click id checkbox

			expect(checkboxes[0]).toBeChecked();
			expect(screen.getByText(/selected \(1\)/i)).toBeInTheDocument();
		});

		it('should deselect a column when checkbox is clicked again', async () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: partialConfig
				}
			});

			const checkboxes = screen.getAllByRole('checkbox');
			await fireEvent.click(checkboxes[0]); // Unclick id checkbox

			expect(checkboxes[0]).not.toBeChecked();
			expect(screen.getByText(/selected \(1\)/i)).toBeInTheDocument();
		});

		it('should toggle column when label is clicked', async () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			const labels = screen.getAllByText(/^(id|name|age|email)$/);
			await fireEvent.click(labels[0].closest('label')!);

			const checkboxes = screen.getAllByRole('checkbox');
			expect(checkboxes[0]).toBeChecked();
		});
	});

	describe('select all/deselect all', () => {
		it('should select all columns when Select All is clicked', async () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			const selectAllButton = screen.getByRole('button', { name: /select all/i });
			await fireEvent.click(selectAllButton);

			const checkboxes = screen.getAllByRole('checkbox');
			checkboxes.forEach((checkbox) => {
				expect(checkbox).toBeChecked();
			});

			expect(screen.getByText(/selected \(4\)/i)).toBeInTheDocument();
		});

		it('should deselect all columns when Deselect All is clicked', async () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: fullConfig
				}
			});

			const deselectAllButton = screen.getByRole('button', { name: /deselect all/i });
			await fireEvent.click(deselectAllButton);

			const checkboxes = screen.getAllByRole('checkbox');
			checkboxes.forEach((checkbox) => {
				expect(checkbox).not.toBeChecked();
			});

			expect(screen.queryByText(/selected/i)).not.toBeInTheDocument();
		});

		it('should select all when starting from partial selection', async () => {
			render(SelectConfig, {
				props: {
					schema: mockSchema,
					config: partialConfig
				}
			});

			const selectAllButton = screen.getByRole('button', { name: /select all/i });
			await fireEvent.click(selectAllButton);

			const checkboxes = screen.getAllByRole('checkbox');
			checkboxes.forEach((checkbox) => {
				expect(checkbox).toBeChecked();
			});
		});
	});
});
