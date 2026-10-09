import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { ComputeWorkerStatusResponse } from '$lib/types/compute';

const mockConnectComputeWorkersStream = vi.fn();
const mockShutdownComputeWorker = vi.fn();

vi.mock('$lib/api/compute', () => ({
	connectComputeWorkersStream: (...args: unknown[]) => mockConnectComputeWorkersStream(...args),
	shutdownComputeWorkerByIdentity: (...args: unknown[]) => mockShutdownComputeWorker(...args)
}));

const { ComputeWorkersStore } = await import('./compute-workers.svelte');

function makeComputeWorker(
	overrides: Partial<ComputeWorkerStatusResponse> = {}
): ComputeWorkerStatusResponse {
	return {
		analysis_id: `analysis-${crypto.randomUUID().slice(0, 8)}`,
		resource_id: overrides.analysis_id ?? `analysis-${crypto.randomUUID().slice(0, 8)}`,
		status: 'healthy',
		container_id: 'container-1234',
		image_digest: 'sha256:abc',
		lifecycle_status: 'idle',
		termination_reason: null,
		exit_code: null,
		oom_killed: null,
		supervisor_id: 'worker-1',
		owner_id: 'worker-1',
		docker_host: 'local',
		last_activity: Temporal.Now.instant().toString(),
		current_job_id: null,
		resource_config: null,
		effective_resources: null,
		defaults: null,
		scope: null,
		reuse_policy: null,
		datasource_id: null,
		build_id: null,
		current_build_id: null,
		current_compute_worker_run_id: null,
		...overrides
	};
}

function mockStreamConnection() {
	const callbacks: {
		onSnapshot: (computeWorkers: ComputeWorkerStatusResponse[]) => void;
		onError: (error: string) => void;
		onClose: () => void;
	}[] = [];
	const close = vi.fn();

	mockConnectComputeWorkersStream.mockImplementation((nextCallbacks) => {
		callbacks.push(
			nextCallbacks as {
				onSnapshot: (computeWorkers: ComputeWorkerStatusResponse[]) => void;
				onError: (error: string) => void;
				onClose: () => void;
			}
		);
		return { close };
	});

	return {
		close,
		emitSnapshot(computeWorkers: ComputeWorkerStatusResponse[]) {
			callbacks.at(-1)?.onSnapshot(computeWorkers);
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
	mockShutdownComputeWorker.mockReturnValue({
		match: (onOk: () => void) => {
			onOk();
			return Promise.resolve();
		}
	});
}

function mockShutdownError(message: string, status?: number) {
	mockShutdownComputeWorker.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string; status?: number }) => void) => {
			onErr({ message, status });
			return Promise.resolve();
		}
	});
}

describe('ComputeWorkersStore', () => {
	let store: InstanceType<typeof ComputeWorkersStore>;

	beforeEach(() => {
		vi.useFakeTimers();
		vi.clearAllMocks();
		store = new ComputeWorkersStore();
	});

	afterEach(() => {
		store.reset();
		vi.useRealTimers();
	});

	test('starts in a disconnected empty state', () => {
		expect(store.computeWorkers).toEqual([]);
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

		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(1);
		expect(store.isStreaming).toBe(true);
		expect(store.loading).toBe(true);
		expect(store.status).toBe('connecting');
	});

	test('loadSnapshotOnce applies the initial snapshot and closes its socket', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' })];

		store.loadSnapshotOnce();
		store.loadSnapshotOnce();
		stream.emitSnapshot(computeWorkers);
		store.loadSnapshotOnce();

		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.count).toBe(1);
		expect(store.isStreaming).toBe(false);
		expect(store.status).toBe('connected');
		expect(stream.close).toHaveBeenCalledOnce();
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledOnce();
	});

	test('starting the live stream cancels a pending snapshot', () => {
		const snapshotStream = mockStreamConnection();
		store.loadSnapshotOnce();

		const liveStream = mockStreamConnection();
		store.startStream();
		const staleEngine = makeComputeWorker({ analysis_id: 'stale', resource_id: 'stale' });
		snapshotStream.emitSnapshot([staleEngine]);

		expect(snapshotStream.close).toHaveBeenCalled();
		expect(store.computeWorkers).toEqual([]);

		const engine = makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' });
		liveStream.emitSnapshot([engine]);
		expect(store.computeWorkers).toEqual([engine]);
		expect(store.isStreaming).toBe(true);
	});

	test('refreshSnapshot reloads a settled snapshot without starting the live stream', () => {
		const firstStream = mockStreamConnection();
		store.loadSnapshotOnce();
		firstStream.emitSnapshot([]);
		store.refreshSnapshot();
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledOnce();

		vi.advanceTimersByTime(15_000);

		const refreshStream = mockStreamConnection();
		store.refreshSnapshot();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-2', resource_id: 'a-2' })];
		refreshStream.emitSnapshot(computeWorkers);

		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(2);
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.isStreaming).toBe(false);
		expect(refreshStream.close).toHaveBeenCalledOnce();
	});

	test('refreshSnapshot leaves engines untouched while the live stream is active', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' })];

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		store.refreshSnapshot();

		expect(mockConnectComputeWorkersStream).toHaveBeenCalledOnce();
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.isStreaming).toBe(true);
	});

	test('snapshot updates engines and connection state', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [
			makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' }),
			makeComputeWorker({ analysis_id: 'a-2', resource_id: 'a-2' })
		];

		store.startStream();
		stream.emitSnapshot(computeWorkers);

		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.count).toBe(2);
		expect(store.loading).toBe(false);
		expect(store.error).toBeNull();
		expect(store.status).toBe('connected');
	});

	test('errors set error state without clearing existing engines', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1' })];

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		stream.emitError('socket failed');

		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.error).toBe('socket failed');
		expect(store.status).toBe('error');
	});

	test('authentication errors stop reconnect looping after close', () => {
		const stream = mockStreamConnection();

		store.startStream();
		stream.emitError('Not authenticated');
		stream.emitClose();
		vi.advanceTimersByTime(1_000);

		expect(store.error).toBe('Not authenticated');
		expect(store.status).toBe('disconnected');
		expect(store.isStreaming).toBe(false);
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(1);
	});

	test('unexpected close schedules reconnect', () => {
		const first = mockStreamConnection();

		store.startStream();
		first.emitClose();

		expect(store.status).toBe('connecting');
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(1);

		vi.advanceTimersByTime(1_000);
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(2);
		expect(store.status).toBe('connecting');
	});

	test('stopStream holds the socket until engines drain', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1' })];

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		store.stopStream();
		vi.advanceTimersByTime(1_000);

		expect(stream.close).not.toHaveBeenCalled();
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(1);
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.status).toBe('connected');
		expect(store.isStreaming).toBe(true);

		stream.emitSnapshot([]);
		expect(stream.close).toHaveBeenCalledTimes(1);
		stream.emitClose();
		expect(store.computeWorkers).toEqual([]);
		expect(store.error).toBeNull();
		expect(store.status).toBe('disconnected');
		expect(store.isStreaming).toBe(false);
	});

	test('shutdownComputeWorker removes the engine from the local snapshot', async () => {
		const stream = mockStreamConnection();
		const computeWorkers = [
			makeComputeWorker({ analysis_id: 'a-1' }),
			makeComputeWorker({ analysis_id: 'a-2' })
		];
		mockShutdownSuccess();

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		await store.shutdownComputeWorker(computeWorkers[0]!);

		expect(store.computeWorkers).toHaveLength(1);
		expect(store.computeWorkers[0]?.analysis_id).toBe('a-2');
	});

	test('shutdownComputeWorker keeps the row until the API confirms shutdown', async () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' })];
		let resolveShutdown!: () => void;
		mockShutdownComputeWorker.mockReturnValue({
			match: (onOk: () => void) =>
				new Promise<void>((resolve) => {
					resolveShutdown = () => {
						onOk();
						resolve();
					};
				})
		});

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		const shutdown = store.shutdownComputeWorker(computeWorkers[0]!);

		expect(store.computeWorkers).toEqual(computeWorkers);
		resolveShutdown();
		await shutdown;

		expect(store.computeWorkers).toEqual([]);
	});

	test('shutdownComputeWorker keeps a pending engine hidden across snapshots', async () => {
		const stream = mockStreamConnection();
		const computeWorkers = [
			makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' }),
			makeComputeWorker({ analysis_id: 'a-2', resource_id: 'a-2' })
		];
		mockShutdownSuccess();

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		await store.shutdownComputeWorker(computeWorkers[0]!);
		stream.emitSnapshot(computeWorkers);

		expect(store.computeWorkers).toHaveLength(1);
		expect(store.computeWorkers[0]?.analysis_id).toBe('a-2');

		stream.emitSnapshot([makeComputeWorker({ analysis_id: 'a-2', resource_id: 'a-2' })]);
		stream.emitSnapshot(computeWorkers);

		expect(store.computeWorkers).toHaveLength(2);
	});

	test('shutdownComputeWorker surfaces API failures', async () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' })];
		mockShutdownError('Permission denied');

		store.startStream();
		stream.emitSnapshot(computeWorkers);

		await expect(store.shutdownComputeWorker(computeWorkers[0]!)).rejects.toThrow(
			'Permission denied'
		);
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.error).toBe('Permission denied');
		stream.emitSnapshot(computeWorkers);
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.error).toBeNull();
	});

	test('shutdownComputeWorker ignores not-found races', async () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1', resource_id: 'a-1' })];
		mockShutdownError('Compute worker not found', 404);

		store.startStream();
		stream.emitSnapshot(computeWorkers);

		await expect(store.shutdownComputeWorker(computeWorkers[0]!)).resolves.toBeUndefined();
		expect(store.computeWorkers).toEqual([]);
		expect(store.error).toBeNull();
	});

	test('multiple subscribers keep the stream alive until all unsubscribe and engines drain', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1' })];

		store.startStream();
		store.startStream();
		stream.emitSnapshot(computeWorkers);
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(1);

		store.stopStream();
		expect(stream.close).not.toHaveBeenCalled();
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.status).toBe('connected');
		expect(store.isStreaming).toBe(true);

		store.stopStream();
		expect(stream.close).not.toHaveBeenCalled();
		expect(store.computeWorkers).toEqual(computeWorkers);
		expect(store.status).toBe('connected');
		expect(store.isStreaming).toBe(true);

		stream.emitSnapshot([]);
		expect(stream.close).toHaveBeenCalledTimes(1);
		stream.emitClose();
		expect(store.computeWorkers).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.isStreaming).toBe(false);
	});

	test('subscriber count does not go below zero while hold-until-empty is active', () => {
		const stream = mockStreamConnection();
		const computeWorkers = [makeComputeWorker({ analysis_id: 'a-1' })];

		store.startStream();
		stream.emitSnapshot(computeWorkers);
		store.stopStream();
		store.stopStream();

		expect(stream.close).not.toHaveBeenCalled();
		expect(store.status).toBe('connected');

		stream.emitSnapshot([]);
		expect(stream.close).toHaveBeenCalledTimes(1);
		stream.emitClose();
		expect(store.status).toBe('disconnected');

		store.startStream();
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(2);
		expect(store.isStreaming).toBe(true);
	});
});
