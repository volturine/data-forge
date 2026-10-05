import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import PipelineMinimap from './PipelineMinimap.svelte';
import type { PipelineStep } from '$lib/types/analysis';

const steps: PipelineStep[] = [
	{ id: 'step-1', type: 'filter', config: {}, is_applied: true },
	{ id: 'step-2', type: 'sort', config: {}, is_applied: false }
];

function node(id: string, top: number, height: number): HTMLElement {
	const el = document.createElement('div');
	el.id = id;
	el.getBoundingClientRect = () => ({ top, height }) as DOMRect;
	el.scrollIntoView = vi.fn();
	return el;
}

/** jsdom has no layout, so the canvas reports a 1000px document scrolled to 250px in a 500px viewport. */
function canvas(): { el: HTMLElement; nodes: Record<string, HTMLElement> } {
	const el = document.createElement('div');
	Object.defineProperties(el, {
		scrollHeight: { value: 1000 },
		clientHeight: { value: 500 },
		scrollTop: { value: 250, writable: true }
	});
	el.getBoundingClientRect = () => ({ top: 0, height: 500 }) as DOMRect;
	// Node rects are viewport-relative: content offset minus scrollTop.
	const nodes = {
		source: node('pipeline-datasource-node', 0 - 250, 100),
		'step-1': node('step-node-step-1', 300 - 250, 100),
		'step-2': node('step-node-step-2', 600 - 250, 100),
		output: node('pipeline-output-node', 900 - 250, 100)
	};
	el.append(...Object.values(nodes));
	return { el, nodes };
}

beforeEach(() => {
	vi.stubGlobal(
		'ResizeObserver',
		class {
			observe() {}
			disconnect() {}
		}
	);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('PipelineMinimap', () => {
	test('places markers at their proportional canvas positions', () => {
		const { el } = canvas();
		render(PipelineMinimap, { props: { steps, canvasEl: el } });

		expect(screen.getByTestId('minimap-marker-source').style.top).toBe('0%');
		expect(screen.getByTestId('minimap-marker-step-1').style.top).toBe('30%');
		expect(screen.getByTestId('minimap-marker-step-2').style.top).toBe('60%');
		expect(screen.getByTestId('minimap-marker-output').style.top).toBe('90%');
		expect(screen.getByTestId('minimap-marker-step-1').style.height).toBe('10%');
	});

	test('shows the visible part of the canvas as a viewport band', () => {
		const { el } = canvas();
		render(PipelineMinimap, { props: { steps, canvasEl: el } });

		const viewport = screen.getByTestId('minimap-viewport');
		expect(viewport.style.top).toBe('25%');
		expect(viewport.style.height).toBe('50%');
	});

	test('scrolls to a node when its marker is clicked', async () => {
		const { el, nodes } = canvas();
		render(PipelineMinimap, { props: { steps, canvasEl: el } });

		await fireEvent.click(screen.getByRole('button', { name: 'Go to 1. Filter' }));

		expect(nodes['step-1'].scrollIntoView).toHaveBeenCalledWith({
			behavior: 'smooth',
			block: 'center'
		});
	});

	test('labels the hovered marker and flags disabled steps', async () => {
		const { el } = canvas();
		render(PipelineMinimap, { props: { steps, canvasEl: el } });

		await fireEvent.pointerEnter(screen.getByTestId('minimap-marker-step-2'));

		expect(screen.getByTestId('minimap-label')).toHaveTextContent('2. Sort (disabled)');
	});
});
