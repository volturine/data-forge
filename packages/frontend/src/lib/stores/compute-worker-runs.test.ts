import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { ComputeWorkerRunsStore } from './compute-worker-runs.svelte';
import type { ComputeWorkerRun } from '$lib/api/compute-worker-runs';

const mockListComputeWorkerRuns = vi.fn();

vi.mock('$lib/api/compute-worker-runs', () => ({
	listComputeWorkerRuns: (...args: unknown[]) => mockListComputeWorkerRuns(...args)
}));

function makeRun(overrides: Partial<ComputeWorkerRun> = {}): ComputeWorkerRun {
	return {
		id: 'run-1',
		analysis_id: null,
		datasource_id: 'ds-1',
		kind: 'build',
		status: 'success',
		request_json: {},
		result_json: null,
		error_message: null,
		created_at: '2024-06-15T12:00:00Z',
		completed_at: '2024-06-15T12:01:00Z',
		duration_ms: 60000,
		step_timings: {},
		query_plan: null,
		progress: 100,
		current_step: null,
		triggered_by: null,
		execution_entries: [],
		...overrides
	};
}

function mockOk(runs: ComputeWorkerRun[]) {
	return {
		match: (onOk: (v: ComputeWorkerRun[]) => void, _onErr: (e: unknown) => void) => onOk(runs)
	};
}

function mockErr(message: string) {
	return {
		match: (_onOk: (v: unknown) => void, onErr: (e: { message: string }) => void) =>
			onErr({ message })
	};
}

function mockPending() {
	const pending: {
		resolve: ((runs: ComputeWorkerRun[]) => void) | null;
		reject: ((error: { message: string }) => void) | null;
	} = { resolve: null, reject: null };
	const result = {
		match: (
			onOk: (runs: ComputeWorkerRun[]) => void,
			onErr: (error: { message: string }) => void
		) => {
			pending.resolve = onOk;
			pending.reject = onErr;
		}
	};
	return { pending, result };
}

describe('ComputeWorkerRunsStore', () => {
	beforeEach(() => {
		mockListComputeWorkerRuns.mockReset();
		mockListComputeWorkerRuns.mockReturnValue(mockOk([]));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	test('initial state', () => {
		const store = new ComputeWorkerRunsStore();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});

	test('load succeeds and forwards params without abort signal churn', () => {
		const runs = [makeRun()];
		mockListComputeWorkerRuns.mockReturnValue(mockOk(runs));

		const store = new ComputeWorkerRunsStore();
		store.load({ datasource_id: 'ds-1', limit: 25 });

		expect(store.status).toBe('connected');
		expect(store.runs).toEqual(runs);
		expect(store.error).toBeNull();
		expect(mockListComputeWorkerRuns).toHaveBeenCalledWith({ datasource_id: 'ds-1', limit: 25 });
	});

	test('load failure sets error state', () => {
		mockListComputeWorkerRuns.mockReturnValue(mockErr('Network error'));

		const store = new ComputeWorkerRunsStore();
		store.load({ datasource_id: 'ds-1' });

		expect(store.status).toBe('error');
		expect(store.error).toBe('Network error');
	});

	test('refresh coalesces while a request is in flight', async () => {
		const first = mockPending();
		mockListComputeWorkerRuns
			.mockReturnValueOnce(first.result)
			.mockReturnValueOnce(mockOk([makeRun()]));

		const store = new ComputeWorkerRunsStore();
		store.load({ datasource_id: 'ds-1' });
		store.refresh();

		expect(mockListComputeWorkerRuns).toHaveBeenCalledTimes(1);
		first.pending.resolve?.([makeRun({ id: 'run-1' })]);
		await Promise.resolve();

		expect(mockListComputeWorkerRuns).toHaveBeenCalledTimes(2);
		expect(store.status).toBe('connected');
	});

	test('stale response from older params is ignored', async () => {
		const first = mockPending();
		const second = mockPending();
		mockListComputeWorkerRuns.mockReturnValueOnce(first.result).mockReturnValueOnce(second.result);

		const store = new ComputeWorkerRunsStore();
		store.load({ datasource_id: 'ds-1' });
		store.load({ datasource_id: 'ds-2' });

		second.pending.resolve?.([makeRun({ id: 'run-2', datasource_id: 'ds-2' })]);
		await Promise.resolve();
		first.pending.resolve?.([makeRun({ id: 'run-1', datasource_id: 'ds-1' })]);
		await Promise.resolve();

		expect(store.status).toBe('connected');
		expect(store.runs.map((run) => run.id)).toEqual(['run-2']);
	});

	test('close ignores late results instead of surfacing them as failures', async () => {
		const request = mockPending();
		mockListComputeWorkerRuns.mockReturnValueOnce(request.result);

		const store = new ComputeWorkerRunsStore();
		store.load({ datasource_id: 'ds-1' });
		store.close();
		request.pending.resolve?.([makeRun()]);
		await Promise.resolve();

		expect(store.status).toBe('disconnected');
		expect(store.runs).toEqual([]);
		expect(store.error).toBeNull();
	});

	test('reset clears state', () => {
		mockListComputeWorkerRuns.mockReturnValue(mockOk([makeRun()]));
		const store = new ComputeWorkerRunsStore();
		store.load({ datasource_id: 'ds-1' });
		expect(store.runs).toHaveLength(1);

		store.reset();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});
});
