import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { flushSync } from 'svelte';
import { errAsync, ResultAsync } from 'neverthrow';
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

	test('closing the popup leaves stream ownership with the shell', async () => {
		const stream = mockStreamConnection();
		computeWorkersStore.startStream();
		expect(mockConnectComputeWorkersStream).toHaveBeenCalledTimes(1);
		const view = render(ComputeWorkersPopup, { props: { open: true } });
		flushSync();

		await view.rerender({ open: false });
		await tick();

		expect(stream.close).not.toHaveBeenCalled();
		expect(computeWorkersStore.isStreaming).toBe(true);
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

	test('excludes terminated workers from the idle count and filter', async () => {
		render(ComputeWorkersPopup, { props: { open: true } });
		computeWorkersStore.computeWorkers = [
			makeComputeWorker({ resource_id: 'healthy-idle' }),
			makeComputeWorker({ resource_id: 'healthy-busy', current_job_id: 'job-1' }),
			makeComputeWorker({ resource_id: 'terminated-worker', status: 'terminated' })
		];
		await tick();

		expect(
			screen.getByText('Idle workers', { selector: 'span' }).nextElementSibling?.textContent
		).toBe('1');
		expect(screen.getByText('Terminated')).toBeTruthy();

		await fireEvent.change(screen.getByLabelText('Activity'), { target: { value: 'idle' } });
		expect(screen.getByText('healthy-idle')).toBeTruthy();
		expect(screen.queryByText('terminated-worker')).toBeNull();
	});

	test('searches worker fields case-insensitively and filters by activity', async () => {
		render(ComputeWorkersPopup, { props: { open: true } });
		computeWorkersStore.computeWorkers = [
			makeComputeWorker({
				resource_id: 'analysis-alpha',
				container_id: 'container-alpha',
				docker_host: 'docker-west'
			}),
			makeComputeWorker({
				resource_id: 'datasource-2',
				scope: 'build',
				container_id: 'container-beta',
				docker_host: 'docker-east',
				current_job_id: 'job-91',
				current_build_id: 'build-91'
			})
		];
		await tick();

		const search = screen.getByRole('searchbox', { name: 'Search compute workers' });
		await fireEvent.input(search, { target: { value: 'DOCKER-EAST' } });
		expect(screen.getByText('datasource-2')).toBeTruthy();
		expect(screen.queryByText('analysis-alpha')).toBeNull();

		await fireEvent.input(search, { target: { value: 'build-91' } });
		expect(screen.getByText('datasource-2')).toBeTruthy();
		expect(screen.queryByText('analysis-alpha')).toBeNull();

		await fireEvent.input(search, { target: { value: '' } });
		await fireEvent.change(screen.getByLabelText('Activity'), { target: { value: 'busy' } });
		expect(screen.getByText('datasource-2')).toBeTruthy();
		expect(screen.queryByText('analysis-alpha')).toBeNull();
		expect(mockShutdownComputeWorker).not.toHaveBeenCalled();
	});

	test('shows a pending snapshot and then the empty state', async () => {
		const stream = mockStreamConnection();
		render(ComputeWorkersPopup, { props: { open: true } });

		computeWorkersStore.loadSnapshotOnce();
		await tick();
		expect(screen.getByText('Loading compute workers...')).toBeTruthy();

		stream.emitSnapshot([]);
		await tick();
		expect(screen.getByText('No compute workers running')).toBeTruthy();
	});

	test('canceling shutdown keeps the compute workers dialog open', async () => {
		computeWorkersStore.computeWorkers = [makeComputeWorker()];
		render(ComputeWorkersPopup, { props: { open: true } });
		await tick();

		await fireEvent.click(
			screen.getByRole('button', { name: 'Shut down idle compute worker analysis-1' })
		);
		expect(screen.getByRole('dialog', { name: 'Compute workers' })).toBeTruthy();
		expect(screen.getByRole('dialog', { name: 'Shut down idle compute worker?' })).toBeTruthy();

		await fireEvent.click(screen.getByRole('button', { name: 'Keep running' }));
		expect(screen.getByRole('dialog', { name: 'Compute workers' })).toBeTruthy();
		expect(screen.queryByRole('dialog', { name: 'Shut down idle compute worker?' })).toBeNull();
		expect(computeWorkersStore.computeWorkers).toHaveLength(1);
	});

	test('keeps shutdown disabled across dialog remount while request is pending', async () => {
		let resolveShutdown: () => void = () => undefined;
		const pendingShutdown = new Promise<void>((resolve) => {
			resolveShutdown = resolve;
		});
		mockShutdownComputeWorker.mockReturnValue(ResultAsync.fromSafePromise(pendingShutdown));
		computeWorkersStore.computeWorkers = [makeComputeWorker()];
		const view = render(ComputeWorkersPopup, { props: { open: true } });
		await tick();

		await fireEvent.click(
			screen.getByRole('button', { name: 'Shut down idle compute worker analysis-1' })
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Shut down' }));
		await waitFor(() => expect(mockShutdownComputeWorker).toHaveBeenCalledTimes(1));

		await view.rerender({ open: false });
		await tick();
		await view.rerender({ open: true });
		await tick();

		const shutdownButton = screen.getByRole('button', {
			name: 'Shut down idle compute worker analysis-1'
		});
		expect(shutdownButton).toBeDisabled();
		expect(mockShutdownComputeWorker).toHaveBeenCalledTimes(1);

		resolveShutdown();
		await waitFor(() => expect(screen.getByText('No compute workers running')).toBeTruthy());
	});

	test('shows shutdown errors and reenables the action without an unhandled rejection', async () => {
		mockShutdownComputeWorker.mockReturnValue(
			errAsync({ message: 'Shutdown failed', status: 500 })
		);
		computeWorkersStore.computeWorkers = [makeComputeWorker()];
		render(ComputeWorkersPopup, { props: { open: true } });
		await tick();

		await fireEvent.click(
			screen.getByRole('button', { name: 'Shut down idle compute worker analysis-1' })
		);
		await fireEvent.click(screen.getByRole('button', { name: 'Shut down' }));
		await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Shutdown failed'));

		expect(
			screen.getByRole('button', { name: 'Shut down idle compute worker analysis-1' })
		).not.toBeDisabled();
	});

	test('clears search and activity filters after closing and reopening', async () => {
		const view = render(ComputeWorkersPopup, { props: { open: true } });
		const search = screen.getByRole('searchbox', { name: 'Search compute workers' });
		await fireEvent.input(search, { target: { value: 'analysis-1' } });
		await fireEvent.change(screen.getByLabelText('Activity'), { target: { value: 'busy' } });

		await view.rerender({ open: false });
		await tick();
		await view.rerender({ open: true });
		await tick();

		expect(screen.getByRole('searchbox', { name: 'Search compute workers' })).toHaveProperty(
			'value',
			''
		);
		expect(screen.getByLabelText('Activity')).toHaveProperty('value', 'all');
	});

	test('renders store errors as an alert', async () => {
		const { getByRole } = render(ComputeWorkersPopup, { props: { open: true } });
		computeWorkersStore.error = 'Worker status stream failed';
		await tick();
		expect(getByRole('alert').textContent).toContain('Worker status stream failed');
	});
});
