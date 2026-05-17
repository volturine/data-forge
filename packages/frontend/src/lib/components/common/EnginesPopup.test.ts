import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { flushSync } from 'svelte';
import type { EngineStatusResponse } from '$lib/types/compute';

const mockConnectEnginesStream = vi.fn();
const mockShutdownEngine = vi.fn();

vi.mock('$lib/api/compute', () => ({
	connectEnginesStream: (...args: unknown[]) => mockConnectEnginesStream(...args),
	shutdownEngine: (...args: unknown[]) => mockShutdownEngine(...args)
}));

const { enginesStore } = await import('$lib/stores/engines.svelte');
const { default: EnginesPopup } = await import('./EnginesPopup.svelte');

function makeEngine(overrides: Partial<EngineStatusResponse> = {}): EngineStatusResponse {
	return {
		analysis_id: 'analysis-1',
		status: 'healthy',
		process_id: 1234,
		last_activity: new Date().toISOString(),
		current_job_id: null,
		resource_config: null,
		effective_resources: null,
		defaults: null,
		...overrides
	};
}

function mockStreamConnection() {
	const callbacks: {
		onSnapshot: (engines: EngineStatusResponse[]) => void;
		onError: (error: string) => void;
		onClose: () => void;
	}[] = [];
	const close = vi.fn();

	mockConnectEnginesStream.mockImplementation((nextCallbacks) => {
		callbacks.push(
			nextCallbacks as {
				onSnapshot: (engines: EngineStatusResponse[]) => void;
				onError: (error: string) => void;
				onClose: () => void;
			}
		);
		return { close };
	});

	return {
		close,
		emitSnapshot(engines: EngineStatusResponse[]) {
			callbacks.at(-1)?.onSnapshot(engines);
		},
		emitError(message: string) {
			callbacks.at(-1)?.onError(message);
		},
		emitClose() {
			callbacks.at(-1)?.onClose();
		}
	};
}

describe('EnginesPopup', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		enginesStore.reset();
	});

	afterEach(() => {
		enginesStore.reset();
	});

	test('opening the popup reflects store state without creating its own stream', async () => {
		render(EnginesPopup, { props: { open: true } });
		flushSync();
		expect(mockConnectEnginesStream).not.toHaveBeenCalled();
		enginesStore.engines = [makeEngine()];
		enginesStore.status = 'connected';
		await tick();
		expect(enginesStore.engines).toHaveLength(1);
		expect(enginesStore.status).toBe('connected');
	});

	test('closing the popup stops the stream', async () => {
		const stream = mockStreamConnection();
		const view = render(EnginesPopup, { props: { open: true } });
		flushSync();

		await view.rerender({ open: false });
		await tick();

		expect(stream.close).not.toHaveBeenCalled();
		stream.emitSnapshot([]);
		stream.emitClose();
		expect(enginesStore.status).toBe('disconnected');
		expect(enginesStore.engines).toEqual([]);
	});
});
