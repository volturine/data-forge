import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { flushSync } from 'svelte';
import type { ComputeWorkerStatusResponse } from '$lib/types/compute';

const mockConnectComputeWorkersStream = vi.fn();
const mockShutdownComputeWorker = vi.fn();

vi.mock('$lib/api/compute', () => ({
	connectComputeWorkersStream: (...args: unknown[]) => mockConnectComputeWorkersStream(...args),
	shutdownComputeWorkerByIdentity: (...args: unknown[]) => mockShutdownComputeWorker(...args)
}));

const { computeWorkersStore } = await import('$lib/stores/compute-workers.svelte');
const { default: ComputeWorkersPopup } = await import('./ComputeWorkersPopup.svelte');

function makeComputeWorker(
	overrides: Partial<ComputeWorkerStatusResponse> = {}
): ComputeWorkerStatusResponse {
	return {
		analysis_id: 'analysis-1',
		resource_id: 'analysis-1',
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

describe('ComputeWorkersPopup', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		computeWorkersStore.reset();
	});

	afterEach(() => {
		computeWorkersStore.reset();
	});

	test('opening the popup reflects store state without creating its own stream', async () => {
		render(ComputeWorkersPopup, { props: { open: true } });
		flushSync();
		expect(mockConnectComputeWorkersStream).not.toHaveBeenCalled();
		computeWorkersStore.computeWorkers = [makeComputeWorker()];
		computeWorkersStore.status = 'connected';
		await tick();
		expect(computeWorkersStore.computeWorkers).toHaveLength(1);
		expect(computeWorkersStore.status).toBe('connected');
	});

	test('closing the popup stops the stream', async () => {
		const stream = mockStreamConnection();
		const view = render(ComputeWorkersPopup, { props: { open: true } });
		flushSync();

		await view.rerender({ open: false });
		await tick();

		expect(stream.close).not.toHaveBeenCalled();
		stream.emitSnapshot([]);
		stream.emitClose();
		expect(computeWorkersStore.status).toBe('disconnected');
		expect(computeWorkersStore.computeWorkers).toEqual([]);
	});

	test('shows Idle for warm engines and Job running when current_job_id is set', async () => {
		const { getByText } = render(ComputeWorkersPopup, { props: { open: true } });
		computeWorkersStore.computeWorkers = [
			makeComputeWorker({ resource_id: 'idle-1', current_job_id: null }),
			makeComputeWorker({ resource_id: 'busy-1', current_job_id: 'job-9' })
		];
		computeWorkersStore.status = 'connected';
		await tick();
		flushSync();
		expect(getByText('Idle')).toBeTruthy();
		expect(getByText('Job running')).toBeTruthy();
	});
});
