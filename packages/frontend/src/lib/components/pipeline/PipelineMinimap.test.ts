import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import PipelineMinimap from './PipelineMinimap.svelte';
import type { PipelineStep } from '$lib/types/analysis';

describe('PipelineMinimap', () => {
	const mockSteps: PipelineStep[] = [
		{ id: 'step-1', type: 'filter', config: { condition: 'x > 1' }, is_applied: true },
		{ id: 'step-2', type: 'aggregate', config: { group_by: ['a'] }, is_applied: false },
		{ id: 'step-3', type: 'sort', config: { columns: ['b'] }, is_applied: true }
	];

	test('renders correct step count label', () => {
		const { rerender } = render(PipelineMinimap, {
			props: { steps: [] }
		});
		expect(screen.getByTestId('canvas-step-count')).toHaveTextContent('0 steps');

		rerender({ steps: [mockSteps[0]] });
		expect(screen.getByTestId('canvas-step-count')).toHaveTextContent('1 step');

		rerender({ steps: mockSteps });
		expect(screen.getByTestId('canvas-step-count')).toHaveTextContent('3 steps');
	});

	test('toggles minimap visibility when toggle button is clicked', async () => {
		render(PipelineMinimap, {
			props: { steps: mockSteps }
		});

		expect(screen.getByTestId('pipeline-minimap')).toBeInTheDocument();

		const toggleButton = screen.getByTestId('minimap-toggle');
		await fireEvent.click(toggleButton);

		expect(screen.queryByTestId('pipeline-minimap')).not.toBeInTheDocument();
		expect(screen.getByTestId('canvas-step-count')).toBeInTheDocument();

		await fireEvent.click(toggleButton);
		expect(screen.getByTestId('pipeline-minimap')).toBeInTheDocument();
	});

	test('scrolls to nodes and triggers onStepClick when minimap items are clicked', async () => {
		const onStepClick = vi.fn();
		const container = document.createElement('div');
		const dsNode = document.createElement('div');
		dsNode.id = 'pipeline-datasource-node';
		dsNode.scrollIntoView = vi.fn();

		const stepNode1 = document.createElement('div');
		stepNode1.id = 'step-node-step-1';
		stepNode1.scrollIntoView = vi.fn();

		const outputNode = document.createElement('div');
		outputNode.id = 'pipeline-output-node';
		outputNode.scrollIntoView = vi.fn();

		container.appendChild(dsNode);
		container.appendChild(stepNode1);
		container.appendChild(outputNode);

		render(PipelineMinimap, {
			props: {
				steps: mockSteps,
				canvasEl: container,
				onStepClick
			}
		});

		await fireEvent.click(screen.getByTestId('minimap-datasource'));
		expect(dsNode.scrollIntoView).toHaveBeenCalled();

		await fireEvent.click(screen.getByTestId('minimap-step-step-1'));
		expect(stepNode1.scrollIntoView).toHaveBeenCalled();
		expect(onStepClick).toHaveBeenCalledWith('step-1');

		await fireEvent.click(screen.getByTestId('minimap-output'));
		expect(outputNode.scrollIntoView).toHaveBeenCalled();
	});
});
