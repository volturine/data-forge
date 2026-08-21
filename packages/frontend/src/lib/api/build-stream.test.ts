import { beforeEach, describe, expect, test, vi } from 'vitest';
import type { BuildEvent } from '$lib/types/build-stream';
import type { StreamCallbacks } from './websocket';

type StreamOptions = {
	parse: (data: string) => unknown | null;
	isSnapshot: (msg: unknown) => boolean;
	extractSnapshot: (msg: unknown) => unknown;
	extractEvent?: (msg: unknown) => unknown;
	callbacks: StreamCallbacks<unknown, unknown>;
};

let options: StreamOptions;

vi.mock('./client', () => ({
	apiRequest: vi.fn()
}));

vi.mock('./websocket', () => ({
	createStream: (_endpoint: string, streamOptions: StreamOptions) => {
		options = streamOptions;
		return { close: () => {} };
	},
	createOwnedWebSocket: vi.fn(),
	closeOwnedWebSocket: vi.fn()
}));

const { connectBuildDetailStream } = await import('./build-stream');

function dispatchMessage(data: string): void {
	const msg = options.parse(data);
	if (!msg) return;
	if (options.isSnapshot(msg)) {
		options.callbacks.onSnapshot(options.extractSnapshot(msg));
		return;
	}
	if (
		typeof msg === 'object' &&
		msg !== null &&
		(msg as Record<string, unknown>).type === 'error'
	) {
		options.callbacks.onError((msg as Record<string, string>).error);
		return;
	}
	if (options.extractEvent && options.callbacks.onEvent) {
		options.callbacks.onEvent(options.extractEvent(msg));
	}
}

function progressEvent(context: Record<string, unknown>): string {
	return JSON.stringify({
		context,
		progress: { progress: 50, elapsedMs: 100 }
	});
}

function connect(callbacks: Partial<StreamCallbacks<unknown, unknown>> = {}): void {
	connectBuildDetailStream('build-1', 0, {
		onSnapshot: callbacks.onSnapshot ?? (() => {}),
		onEvent: callbacks.onEvent as (event: BuildEvent) => void,
		onError: callbacks.onError ?? (() => {}),
		onClose: callbacks.onClose ?? (() => {})
	});
}

describe('connectBuildDetailStream', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test('routes invalid JSON through onError instead of throwing', () => {
		const onEvent = vi.fn();
		const onError = vi.fn();
		connect({ onEvent, onError });

		expect(() => dispatchMessage('not json')).not.toThrow();

		expect(onError).toHaveBeenCalledWith('Invalid build stream message');
		expect(onEvent).not.toHaveBeenCalled();
	});

	test('routes events that fail conversion through onError instead of throwing', () => {
		const onEvent = vi.fn();
		const onError = vi.fn();
		connect({ onEvent, onError });

		const malformed = JSON.stringify({
			context: {},
			progress: { progress: 50, elapsedMs: 100 }
		});
		expect(() => dispatchMessage(malformed)).not.toThrow();

		expect(onError).toHaveBeenCalledWith('Invalid build stream event');
		expect(onEvent).not.toHaveBeenCalled();
	});

	test('delivers valid protocol events to onEvent', () => {
		const onEvent = vi.fn();
		const onError = vi.fn();
		connect({ onEvent, onError });

		dispatchMessage(
			progressEvent({
				buildId: 'build-1',
				analysisId: 'analysis-1',
				emittedAt: '2024-01-01T00:00:00Z'
			})
		);

		expect(onError).not.toHaveBeenCalled();
		expect(onEvent).toHaveBeenCalledWith(
			expect.objectContaining({ type: 'progress', progress: 50 } satisfies Partial<BuildEvent>)
		);
	});
});
