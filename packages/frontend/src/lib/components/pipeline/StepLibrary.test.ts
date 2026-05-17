import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import StepLibrary from './StepLibrary.svelte';

describe('StepLibrary', () => {
	test('click adds a step when editable', async () => {
		const onAddStep = vi.fn();
		const onInsertStep = vi.fn();

		render(StepLibrary, {
			props: {
				onAddStep,
				onInsertStep
			}
		});

		const filterButton = screen.getByRole('button', { name: /filter/i });
		await fireEvent.click(filterButton);

		expect(onAddStep).toHaveBeenCalledWith('filter');
		expect(onInsertStep).not.toHaveBeenCalled();
	});

	test('does not add a step when readOnly is true', async () => {
		const onAddStep = vi.fn();
		const onInsertStep = vi.fn();

		render(StepLibrary, {
			props: {
				onAddStep,
				onInsertStep,
				readOnly: true
			}
		});

		const filterButton = screen.getByRole('button', { name: /filter/i });
		expect(filterButton).toBeDisabled();
		await fireEvent.click(filterButton);

		expect(onAddStep).not.toHaveBeenCalled();
		expect(onInsertStep).not.toHaveBeenCalled();
	});
});
