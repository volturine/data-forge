import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { EngineRunsStore } from './engine-runs.svelte';
import type { EngineRun } from '$lib/api/engine-runs';

const mockListEngineRuns = vi.fn();

vi.mock('$lib/api/engine-runs', () => ({
	listEngineRuns: (...args: unknown[]) => mockListEngineRuns(...args)
}));

function makeRun(overrides: Partial<EngineRun> = {}): EngineRun {
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

function mockOk(runs: EngineRun[]) {
	return { match: (onOk: (v: EngineRun[]) => void, _onErr: (e: unknown) => void) => onOk(runs) };
}

function mockErr(message: string) {
	return {
		match: (_onOk: (v: unknown) => void, onErr: (e: { message: string }) => void) =>
			onErr({ message })
	};
}

function mockPending() {
	const pending: {
		resolve: ((runs: EngineRun[]) => void) | null;
		reject: ((error: { message: string }) => void) | null;
	} = { resolve: null, reject: null };
	const result = {
		match: (onOk: (runs: EngineRun[]) => void, onErr: (error: { message: string }) => void) => {
			pending.resolve = onOk;
			pending.reject = onErr;
		}
	};
	return { pending, result };
}

describe('EngineRunsStore', () => {
	beforeEach(() => {
		mockListEngineRuns.mockReset();
		mockListEngineRuns.mockReturnValue(mockOk([]));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	test('initial state', () => {
		const store = new EngineRunsStore();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});

	test('load succeeds and forwards params without abort signal churn', () => {
		const runs = [makeRun()];
		mockListEngineRuns.mockReturnValue(mockOk(runs));

		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1', limit: 25 });

		expect(store.status).toBe('connected');
		expect(store.runs).toEqual(runs);
		expect(store.error).toBeNull();
		expect(mockListEngineRuns).toHaveBeenCalledWith({ datasource_id: 'ds-1', limit: 25 });
	});

	test('load failure sets error state', () => {
		mockListEngineRuns.mockReturnValue(mockErr('Network error'));

		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });

		expect(store.status).toBe('error');
		expect(store.error).toBe('Network error');
	});

	test('refresh coalesces while a request is in flight', async () => {
		const first = mockPending();
		mockListEngineRuns.mockReturnValueOnce(first.result).mockReturnValueOnce(mockOk([makeRun()]));

		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });
		store.refresh();

		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);
		first.pending.resolve?.([makeRun({ id: 'run-1' })]);
		await Promise.resolve();

		expect(mockListEngineRuns).toHaveBeenCalledTimes(2);
		expect(store.status).toBe('connected');
	});

	test('stale response from older params is ignored', async () => {
		const first = mockPending();
		const second = mockPending();
		mockListEngineRuns.mockReturnValueOnce(first.result).mockReturnValueOnce(second.result);

		const store = new EngineRunsStore();
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
		mockListEngineRuns.mockReturnValueOnce(request.result);

		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });
		store.close();
		request.pending.resolve?.([makeRun()]);
		await Promise.resolve();

		expect(store.status).toBe('disconnected');
		expect(store.runs).toEqual([]);
		expect(store.error).toBeNull();
	});

	test('reset clears state', () => {
		mockListEngineRuns.mockReturnValue(mockOk([makeRun()]));
		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });
		expect(store.runs).toHaveLength(1);

		store.reset();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});
});
