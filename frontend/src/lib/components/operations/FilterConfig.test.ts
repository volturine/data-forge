import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import FilterConfig from './FilterConfig.svelte';
import type { Schema } from '$lib/types/schema';

describe('FilterConfig', () => {
	const mockSchema: Schema = {
		columns: [
			{ name: 'id', dtype: 'Int64', nullable: false },
			{ name: 'name', dtype: 'String', nullable: true },
			{ name: 'age', dtype: 'Int32', nullable: false },
			{ name: 'salary', dtype: 'Float64', nullable: true }
		],
		row_count: 100
	};

	const emptyConfig = {
		conditions: [],
		logic: 'AND' as const
	};

	const sampleConfig = {
		conditions: [
			{ column: 'age', operator: '>', value: '25' },
			{ column: 'name', operator: 'contains', value: 'John' }
		],
		logic: 'OR' as const
	};

	describe('rendering', () => {
		it('should render with empty config', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			expect(screen.getByText('Filter Configuration')).toBeInTheDocument();
			expect(screen.getByText('Combine conditions with:')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: /add condition/i })).toBeInTheDocument();
		});

		it('should render with initial condition when config is empty', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			const selects = screen.getAllByRole('combobox');
			expect(selects.length).toBeGreaterThan(0);
		});

		it('should render existing conditions from config', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: sampleConfig
				}
			});

			const removeButtons = screen.getAllByRole('button', { name: /remove/i });
			expect(removeButtons).toHaveLength(2);
		});

		it('should display all schema columns in dropdown', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			expect(screen.getByText('id (Int64)')).toBeInTheDocument();
			expect(screen.getByText('name (String)')).toBeInTheDocument();
			expect(screen.getByText('age (Int32)')).toBeInTheDocument();
			expect(screen.getByText('salary (Float64)')).toBeInTheDocument();
		});
	});

	describe('adding and removing conditions', () => {
		it('should add a new condition when Add Condition is clicked', async () => {
			const { container } = render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: { conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' }
				}
			});

			const addButton = screen.getByRole('button', { name: /add condition/i });
			await fireEvent.click(addButton);

			const conditionRows = container.querySelectorAll('.condition-row');
			expect(conditionRows).toHaveLength(2);
		});

		it('should remove a condition when Remove is clicked', async () => {
			const { container } = render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: sampleConfig
				}
			});

			const removeButtons = screen.getAllByRole('button', { name: /remove/i });
			await fireEvent.click(removeButtons[0]);

			const conditionRows = container.querySelectorAll('.condition-row');
			expect(conditionRows).toHaveLength(1);
		});

		it('should disable remove button when only one condition exists', async () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: { conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' }
				}
			});

			const removeButton = screen.getByRole('button', { name: /remove/i });
			expect(removeButton).toBeDisabled();
		});
	});

	describe('changing operators and values', () => {
		it('should display all available operators', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: { conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' }
				}
			});

			const operators = ['=', '!=', '>', '<', '>=', '<=', 'contains'];
			operators.forEach((op) => {
				expect(screen.getByText(op)).toBeInTheDocument();
			});
		});

		it('should use number input for numeric columns', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: { conditions: [{ column: 'age', operator: '>', value: '25' }], logic: 'AND' }
				}
			});

			const inputs = screen.getAllByPlaceholderText('Value');
			expect(inputs[0]).toHaveAttribute('type', 'number');
		});

		it('should use text input for string columns', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: {
						conditions: [{ column: 'name', operator: 'contains', value: 'John' }],
						logic: 'AND'
					}
				}
			});

			const inputs = screen.getAllByPlaceholderText('Value');
			expect(inputs[0]).toHaveAttribute('type', 'text');
		});
	});

	describe('logic toggle', () => {
		it('should default to AND logic', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: emptyConfig
				}
			});

			const logicSelect = screen.getByRole('combobox', { name: /combine conditions with/i });
			expect(logicSelect).toHaveValue('AND');
		});

		it('should display OR logic when configured', () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: sampleConfig
				}
			});

			const logicSelect = screen.getByRole('combobox', { name: /combine conditions with/i });
			expect(logicSelect).toHaveValue('OR');
		});

		it('should allow toggling between AND and OR', async () => {
			render(FilterConfig, {
				props: {
					schema: mockSchema,
					config: { conditions: [{ column: '', operator: '=', value: '' }], logic: 'AND' }
				}
			});

			const logicSelect = screen.getByRole('combobox', { name: /combine conditions with/i });
			await fireEvent.change(logicSelect, { target: { value: 'OR' } });

			expect(logicSelect).toHaveValue('OR');
		});
	});
});
