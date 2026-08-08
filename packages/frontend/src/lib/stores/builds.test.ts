import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { BuildsStore } from './builds.svelte';
import type { BuildRunSummary } from '$lib/types/build-stream';

const mockListBuilds = vi.fn();

vi.mock('$lib/api/builds', () => ({
	listBuilds: (...args: unknown[]) => mockListBuilds(...args)
}));

function makeBuild(overrides: Partial<BuildRunSummary> = {}): BuildRunSummary {
	return {
		build_id: 'build-1',
		analysis_id: 'analysis-1',
		analysis_name: 'Analysis 1',
		namespace: 'default',
		status: 'completed',
		started_at: '2024-06-15T12:00:00Z',
		starter: { user_id: null, display_name: null, email: null, triggered_by: null },
		resource_config: null,
		progress: 1,
		elapsed_ms: 60000,
		estimated_remaining_ms: null,
		current_step: null,
		current_step_index: null,
		total_steps: 0,
		current_kind: 'build',
		current_datasource_id: 'ds-1',
		current_tab_id: null,
		current_tab_name: null,
		current_output_id: 'ds-1',
		current_output_name: 'Output',
		current_engine_run_id: null,
		total_tabs: 1,
		cancelled_at: null,
		cancelled_by: null,
		result_json: null,
		...overrides
	};
}

function mockOk(builds: BuildRunSummary[], total: number = builds.length) {
	return {
		match: (
			onOk: (v: { builds: BuildRunSummary[]; total: number }) => void,
			_onErr: (e: unknown) => void
		) => onOk({ builds, total })
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
		resolve: ((value: { builds: BuildRunSummary[]; total: number }) => void) | null;
		reject: ((error: { message: string }) => void) | null;
	} = { resolve: null, reject: null };
	const result = {
		match: (
			onOk: (value: { builds: BuildRunSummary[]; total: number }) => void,
			onErr: (error: { message: string }) => void
		) => {
			pending.resolve = onOk;
			pending.reject = onErr;
		}
	};
	return { pending, result };
}

describe('BuildsStore', () => {
	beforeEach(() => {
		mockListBuilds.mockReset();
		mockListBuilds.mockReturnValue(mockOk([]));
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	test('load succeeds with an empty result instead of failing', () => {
		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });

		expect(store.status).toBe('connected');
		expect(store.builds).toEqual([]);
		expect(store.total).toBe(0);
		expect(store.error).toBeNull();
		expect(mockListBuilds).toHaveBeenCalledWith({ datasource_id: 'ds-1' });
	});

	test('load failure sets error state', () => {
		mockListBuilds.mockReturnValue(mockErr('Server error'));

		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });

		expect(store.status).toBe('error');
		expect(store.error).toBe('Server error');
	});

	test('stale response from older params is ignored', async () => {
		const first = mockPending();
		const second = mockPending();
		mockListBuilds.mockReturnValueOnce(first.result).mockReturnValueOnce(second.result);

		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });
		store.load({ datasource_id: 'ds-2' });

		second.pending.resolve?.({
			builds: [makeBuild({ build_id: 'build-2', current_datasource_id: 'ds-2' })],
			total: 1
		});
		await Promise.resolve();
		first.pending.resolve?.({
			builds: [makeBuild({ build_id: 'build-1', current_datasource_id: 'ds-1' })],
			total: 1
		});
		await Promise.resolve();

		expect(store.status).toBe('connected');
		expect(store.builds.map((build) => build.build_id)).toEqual(['build-2']);
		expect(store.total).toBe(1);
	});

	test('close ignores late results instead of aborting them into red noise', async () => {
		const request = mockPending();
		mockListBuilds.mockReturnValueOnce(request.result);

		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });
		store.close();
		request.pending.resolve?.({ builds: [makeBuild()], total: 1 });
		await Promise.resolve();

		expect(store.status).toBe('disconnected');
		expect(store.builds).toEqual([]);
		expect(store.total).toBe(0);
		expect(store.error).toBeNull();
	});

	test('refresh coalesces while a request is in flight', async () => {
		const first = mockPending();
		mockListBuilds.mockReturnValueOnce(first.result).mockReturnValueOnce(mockOk([makeBuild()], 1));

		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });
		store.refresh();

		expect(mockListBuilds).toHaveBeenCalledTimes(1);
		first.pending.resolve?.({ builds: [makeBuild()], total: 1 });
		await Promise.resolve();

		expect(mockListBuilds).toHaveBeenCalledTimes(2);
		expect(store.status).toBe('connected');
	});

	test('silentRefresh keeps existing rows visible while refetching', async () => {
		const first = mockPending();
		const refreshed = mockPending();
		mockListBuilds.mockReturnValueOnce(first.result).mockReturnValueOnce(refreshed.result);

		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });
		first.pending.resolve?.({ builds: [makeBuild()], total: 1 });
		await Promise.resolve();
		expect(store.status).toBe('connected');

		store.silentRefresh();
		// The store must not flip to 'connecting' (which blanks the table) while the refetch is in flight.
		expect(store.status).toBe('connected');
		expect(store.builds).toHaveLength(1);

		refreshed.pending.resolve?.({
			builds: [makeBuild({ build_id: 'build-2' })],
			total: 1
		});
		await Promise.resolve();
		expect(store.status).toBe('connected');
		expect(store.builds.map((build) => build.build_id)).toEqual(['build-2']);
	});

	test('silentRefresh coalesces behind an in-flight refresh and stays silent', async () => {
		const first = mockPending();
		const second = mockPending();
		mockListBuilds
			.mockReturnValueOnce(first.result)
			.mockReturnValueOnce(second.result)
			.mockReturnValueOnce(mockOk([makeBuild({ build_id: 'build-3' })], 1));

		const store = new BuildsStore();
		store.load({ datasource_id: 'ds-1' });
		first.pending.resolve?.({ builds: [makeBuild()], total: 1 });
		await Promise.resolve();

		store.refresh();
		store.silentRefresh();
		expect(mockListBuilds).toHaveBeenCalledTimes(2);

		second.pending.resolve?.({ builds: [makeBuild({ build_id: 'build-3' })], total: 1 });
		await Promise.resolve();

		expect(mockListBuilds).toHaveBeenCalledTimes(3);
		expect(store.status).toBe('connected');
		expect(store.builds.map((build) => build.build_id)).toEqual(['build-3']);
	});
});
