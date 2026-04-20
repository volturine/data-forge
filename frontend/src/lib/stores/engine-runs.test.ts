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
		kind: 'datasource_update',
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

describe('EngineRunsStore', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		mockListEngineRuns.mockReturnValue(mockOk([]));
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	test('initial state', () => {
		const store = new EngineRunsStore();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});

	test('load sets status to connecting then connected on success', () => {
		const runs = [makeRun()];
		mockListEngineRuns.mockReturnValue(mockOk(runs));

		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });

		expect(store.status).toBe('connected');
		expect(store.runs).toEqual(runs);
		expect(store.error).toBeNull();
		expect(mockListEngineRuns).toHaveBeenCalledWith({ datasource_id: 'ds-1' }, expect.anything());
		store.close();
	});

	test('load sets error status on fetch failure', () => {
		mockListEngineRuns.mockReturnValue(mockErr('Network error'));

		const store = new EngineRunsStore();
		store.load();

		expect(store.status).toBe('error');
		expect(store.error).toBe('Network error');
		store.close();
	});

	test('load performs a single fetch', () => {
		const store = new EngineRunsStore();
		store.load();
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);
		store.close();
	});

	test('close stops in-flight work without refetching', () => {
		const store = new EngineRunsStore();
		store.load();
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);

		store.close();
		vi.advanceTimersByTime(15000);
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);
	});

	test('close when not started is safe', () => {
		const store = new EngineRunsStore();
		expect(() => store.close()).not.toThrow();
	});

	test('reset clears all state and cancels in-flight work', () => {
		const runs = [makeRun()];
		mockListEngineRuns.mockReturnValue(mockOk(runs));

		const store = new EngineRunsStore();
		store.load();
		expect(store.runs).toHaveLength(1);

		store.reset();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();

		vi.advanceTimersByTime(15000);
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);
	});

	test('load refetches when params change', () => {
		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);

		store.load({ datasource_id: 'ds-2' });
		expect(mockListEngineRuns).toHaveBeenCalledTimes(2);
		expect(mockListEngineRuns).toHaveBeenLastCalledWith(
			{ datasource_id: 'ds-2' },
			expect.anything()
		);
		store.close();
	});

	test('load does not refetch when params are unchanged', () => {
		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1', limit: 50 });
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);

		store.load({ datasource_id: 'ds-1', limit: 50 });
		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);
		store.close();
	});

	test('load clears previous error when params change', () => {
		mockListEngineRuns.mockReturnValue(mockErr('fail'));
		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });
		expect(store.error).toBe('fail');

		mockListEngineRuns.mockReturnValue(mockOk([]));
		store.load({ datasource_id: 'ds-2' });
		expect(store.error).toBeNull();
		expect(store.status).toBe('connected');
		store.close();
	});

	test('params are forwarded to listEngineRuns', () => {
		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-42', limit: 25 });
		expect(mockListEngineRuns).toHaveBeenCalledWith(
			{ datasource_id: 'ds-42', limit: 25 },
			expect.anything()
		);
		store.close();
	});

	test('no params calls listEngineRuns with undefined', () => {
		const store = new EngineRunsStore();
		store.load();
		expect(mockListEngineRuns).toHaveBeenCalledWith(undefined, expect.anything());
		store.close();
	});

	test('refresh coalesces while a request is in flight', async () => {
		const pending: { resolve: ((runs: EngineRun[]) => void) | null } = { resolve: null };
		mockListEngineRuns.mockImplementation(() => ({
			match: (onOk: (runs: EngineRun[]) => void) => {
				pending.resolve = onOk;
			}
		}));

		const store = new EngineRunsStore();
		store.load({ datasource_id: 'ds-1' });
		store.refresh();

		expect(mockListEngineRuns).toHaveBeenCalledTimes(1);
		pending.resolve?.([makeRun()]);
		await Promise.resolve();

		expect(mockListEngineRuns).toHaveBeenCalledTimes(2);
		store.close();
	});

	test('subsequent load success updates runs', () => {
		const store = new EngineRunsStore();
		mockListEngineRuns.mockReturnValue(mockOk([makeRun({ id: 'run-1' })]));
		store.load({ datasource_id: 'ds-1' });
		expect(store.runs).toHaveLength(1);

		mockListEngineRuns.mockReturnValue(
			mockOk([makeRun({ id: 'run-1' }), makeRun({ id: 'run-2' })])
		);
		store.load({ datasource_id: 'ds-2' });
		expect(store.runs).toHaveLength(2);
		store.close();
	});

	test('load error after success sets error status', () => {
		const store = new EngineRunsStore();
		mockListEngineRuns.mockReturnValue(mockOk([makeRun()]));
		store.load({ datasource_id: 'ds-1' });
		expect(store.status).toBe('connected');

		mockListEngineRuns.mockReturnValue(mockErr('Server down'));
		store.load({ datasource_id: 'ds-2' });
		expect(store.status).toBe('error');
		expect(store.error).toBe('Server down');
		store.close();
	});
});
