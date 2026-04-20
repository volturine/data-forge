import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { EngineStatusResponse } from '$lib/types/compute';

const mockConnectEnginesStream = vi.fn();
const mockShutdownEngine = vi.fn();

vi.mock('$lib/api/compute', () => ({
	connectEnginesStream: (...args: unknown[]) => mockConnectEnginesStream(...args),
	shutdownEngine: (...args: unknown[]) => mockShutdownEngine(...args)
}));

const { EnginesStore } = await import('./engines.svelte');

function makeEngine(overrides: Partial<EngineStatusResponse> = {}): EngineStatusResponse {
	return {
		analysis_id: `analysis-${crypto.randomUUID().slice(0, 8)}`,
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

function mockShutdownSuccess() {
	mockShutdownEngine.mockReturnValue({
		match: (onOk: () => void) => {
			onOk();
			return Promise.resolve();
		}
	});
}

function mockShutdownError(message: string) {
	mockShutdownEngine.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

describe('EnginesStore', () => {
	let store: InstanceType<typeof EnginesStore>;

	beforeEach(() => {
		vi.useFakeTimers();
		vi.clearAllMocks();
		store = new EnginesStore();
	});

	afterEach(() => {
		store.stopStream();
		vi.useRealTimers();
	});

	test('starts in a disconnected empty state', () => {
		expect(store.engines).toEqual([]);
		expect(store.loading).toBe(false);
		expect(store.error).toBeNull();
		expect(store.status).toBe('disconnected');
		expect(store.count).toBe(0);
		expect(store.isStreaming).toBe(false);
	});

	test('startStream opens a single websocket connection', () => {
		mockStreamConnection();

		store.startStream();
		store.startStream();

		expect(mockConnectEnginesStream).toHaveBeenCalledTimes(1);
		expect(store.isStreaming).toBe(true);
		expect(store.loading).toBe(true);
		expect(store.status).toBe('connecting');
	});

	test('snapshot updates engines and connection state', () => {
		const stream = mockStreamConnection();
		const engines = [makeEngine({ analysis_id: 'a-1' }), makeEngine({ analysis_id: 'a-2' })];

		store.startStream();
		stream.emitSnapshot(engines);

		expect(store.engines).toEqual(engines);
		expect(store.count).toBe(2);
		expect(store.loading).toBe(false);
		expect(store.error).toBeNull();
		expect(store.status).toBe('connected');
	});

	test('errors set error state without clearing existing engines', () => {
		const stream = mockStreamConnection();
		const engines = [makeEngine({ analysis_id: 'a-1' })];

		store.startStream();
		stream.emitSnapshot(engines);
		stream.emitError('socket failed');

		expect(store.engines).toEqual(engines);
		expect(store.error).toBe('socket failed');
		expect(store.status).toBe('error');
	});

	test('unexpected close schedules reconnect', () => {
		const first = mockStreamConnection();

		store.startStream();
		first.emitClose();

		expect(store.status).toBe('connecting');
		expect(mockConnectEnginesStream).toHaveBeenCalledTimes(1);

		vi.advanceTimersByTime(1_000);
		expect(mockConnectEnginesStream).toHaveBeenCalledTimes(2);
		expect(store.status).toBe('connecting');
	});

	test('stopStream closes the socket and cancels reconnects', () => {
		const stream = mockStreamConnection();

		store.startStream();
		store.stopStream();
		vi.advanceTimersByTime(1_000);

		expect(stream.close).toHaveBeenCalledTimes(1);
		expect(mockConnectEnginesStream).toHaveBeenCalledTimes(1);
		expect(store.status).toBe('disconnected');
		expect(store.isStreaming).toBe(false);
	});

	test('shutdownEngine removes the engine from the local snapshot', async () => {
		const stream = mockStreamConnection();
		const engines = [makeEngine({ analysis_id: 'a-1' }), makeEngine({ analysis_id: 'a-2' })];
		mockShutdownSuccess();

		store.startStream();
		stream.emitSnapshot(engines);
		await store.shutdownEngine('a-1');

		expect(store.engines).toHaveLength(1);
		expect(store.engines[0]?.analysis_id).toBe('a-2');
	});

	test('shutdownEngine surfaces API failures', async () => {
		const stream = mockStreamConnection();
		const engines = [makeEngine({ analysis_id: 'a-1' })];
		mockShutdownError('Permission denied');

		store.startStream();
		stream.emitSnapshot(engines);

		await expect(store.shutdownEngine('a-1')).rejects.toThrow('Permission denied');
		expect(store.engines).toEqual(engines);
		expect(store.error).toBe('Permission denied');
	});

	test('multiple subscribers keep the stream alive until all unsubscribe', () => {
		const stream = mockStreamConnection();

		store.startStream();
		store.startStream();
		expect(mockConnectEnginesStream).toHaveBeenCalledTimes(1);

		store.stopStream();
		expect(stream.close).not.toHaveBeenCalled();
		expect(store.status).toBe('connecting');
		expect(store.isStreaming).toBe(true);

		store.stopStream();
		expect(stream.close).toHaveBeenCalledTimes(1);
		expect(store.status).toBe('disconnected');
		expect(store.isStreaming).toBe(false);
	});

	test('subscriber count does not go below zero', () => {
		const stream = mockStreamConnection();

		store.startStream();
		store.stopStream();
		store.stopStream();

		expect(stream.close).toHaveBeenCalledTimes(1);
		expect(store.status).toBe('disconnected');

		store.startStream();
		expect(mockConnectEnginesStream).toHaveBeenCalledTimes(2);
		expect(store.isStreaming).toBe(true);
	});
});
