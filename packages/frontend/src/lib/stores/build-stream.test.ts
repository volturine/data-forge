import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { ActiveBuildDetail } from '$lib/types/build-stream';
import type { BuildRequest } from '$lib/api/compute';

const mockStartActiveBuild = vi.fn();
const mockRetainActivity = vi.fn();
const mockReleaseActivity = vi.fn();

vi.mock('$lib/api/build-stream', async () => {
	const actual =
		await vi.importActual<typeof import('$lib/api/build-stream')>('$lib/api/build-stream');
	return {
		...actual,
		startActiveBuild: (...args: unknown[]) => mockStartActiveBuild(...args)
	};
});

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true
}));

vi.mock('$lib/stores/compute-activity.svelte', () => ({
	computeActivityStore: {
		retain: () => {
			mockRetainActivity();
			return () => mockReleaseActivity();
		}
	}
}));

type Listener = (event?: { data?: string; code?: number; reason?: string }) => void;

class MockWebSocket {
	static instances: MockWebSocket[] = [];

	url: string;
	readyState = 1;
	private listeners = new Map<string, Listener[]>();

	static readonly OPEN = 1;
	static readonly CONNECTING = 0;

	constructor(url: string) {
		this.url = url;
		MockWebSocket.instances.push(this);
	}

	addEventListener(type: string, listener: Listener) {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	close() {
		this.emit('close', { code: 1000, reason: '' });
	}

	emit(type: string, event?: { data?: string; code?: number; reason?: string }) {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event);
		}
	}
}

const BASE = { build_id: 'build-1', analysis_id: 'analysis-1', emitted_at: '2025-01-01T00:00:00Z' };

function msg(socket: MockWebSocket, payload: Record<string, unknown>) {
	socket.emit('message', { data: JSON.stringify({ ...BASE, ...payload }) });
}

const STARTER = { user_id: null, display_name: null, email: null, triggered_by: null };

const DETAIL_BASE: ActiveBuildDetail = {
	build_id: 'build-1',
	analysis_id: 'analysis-1',
	analysis_name: 'My Analysis',
	namespace: 'default',
	status: 'running',
	progress: 0.42,
	started_at: '2025-01-01T00:00:00Z',
	starter: STARTER,
	resource_config: null,
	elapsed_ms: 1200,
	estimated_remaining_ms: 800,
	current_step: 'Loading data',
	current_step_index: 0,
	total_steps: 3,
	current_kind: 'preview',
	current_datasource_id: 'ds-1',
	current_tab_id: 'tab-1',
	current_tab_name: 'Sheet 1',
	current_output_id: 'output-1',
	current_output_name: 'output_sheet_1',
	current_engine_run_id: null,
	total_tabs: 2,
	cancelled_at: null,
	cancelled_by: null,
	steps: [],
	query_plans: [],
	latest_resources: null,
	resources: [],
	logs: [],
	results: [],
	duration_ms: null,
	error: null,
	request_json: null,
	result_json: null
};

const MINIMAL_BUILD_REQUEST = {
	analysis_pipeline: {
		analysis_id: 'analysis-1',
		tabs: []
	}
} satisfies BuildRequest;

const BUILD_REQUEST_WITH_NULL_TAB = {
	...MINIMAL_BUILD_REQUEST,
	tab_id: null
} satisfies BuildRequest;

function makeDetail(overrides: Partial<ActiveBuildDetail> = {}): ActiveBuildDetail {
	return { ...DETAIL_BASE, ...overrides };
}

function mockStartSuccess(detail: ActiveBuildDetail = makeDetail()) {
	mockStartActiveBuild.mockReturnValue({
		match: (onOk: (build: ActiveBuildDetail) => void) => {
			onOk(detail);
			return Promise.resolve();
		}
	});
}

function mockStartError(message: string) {
	mockStartActiveBuild.mockReturnValue({
		match: (_onOk: unknown, onErr: (err: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

const { BuildStreamStore } = await import('./build-stream.svelte');

describe('BuildStreamStore', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.clearAllMocks();
		mockStartSuccess();
		vi.stubGlobal('WebSocket', MockWebSocket);
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	test('initial state', () => {
		const store = new BuildStreamStore();
		expect(store.status).toBe('disconnected');
		expect(store.buildId).toBeNull();
		expect(store.progress).toBe(0);
		expect(store.progressPct).toBe(0);
		expect(store.steps).toEqual([]);
		expect(store.logs).toEqual([]);
		expect(store.queryPlans).toEqual([]);
		expect(store.latestResources).toBeNull();
		expect(store.done).toBe(false);
		expect(store.succeeded).toBe(false);
	});

	test('start requests a live build and connects to its detail stream', () => {
		const store = new BuildStreamStore();
		store.start(BUILD_REQUEST_WITH_NULL_TAB);

		expect(mockRetainActivity).toHaveBeenCalledTimes(1);
		expect(mockStartActiveBuild).toHaveBeenCalledWith({
			analysis_pipeline: {
				analysis_id: 'analysis-1',
				tabs: []
			},
			tab_id: null
		});
		expect(MockWebSocket.instances).toHaveLength(1);
		const socket = MockWebSocket.instances[0];
		expect(socket.url).toContain('/v1/compute/ws/builds/build-1');
	});

	test('watch connects to an existing build detail stream', () => {
		const store = new BuildStreamStore();
		store.watch('build-2');

		expect(mockRetainActivity).toHaveBeenCalledTimes(1);
		expect(MockWebSocket.instances).toHaveLength(1);
		expect(MockWebSocket.instances[0].url).toContain('/v1/compute/ws/builds/build-2');
		expect(store.buildId).toBe('build-2');
		expect(store.status).toBe('connecting');
	});

	test('watch replaces the previous connection', () => {
		const store = new BuildStreamStore();
		store.watch('build-1');
		const first = MockWebSocket.instances[0];

		store.watch('build-2');

		expect(MockWebSocket.instances).toHaveLength(2);
		expect(first.readyState).toBe(1);
		expect(MockWebSocket.instances[1].url).toContain('/v1/compute/ws/builds/build-2');
		expect(store.buildId).toBe('build-2');
	});

	test('stale close from previous connection does not disconnect a new build', () => {
		const store = new BuildStreamStore();
		store.watch('build-1');
		const first = MockWebSocket.instances[0];

		store.start(BUILD_REQUEST_WITH_NULL_TAB);
		const second = MockWebSocket.instances[1];

		first.emit('close', { code: 1000, reason: 'stale close' });
		expect(store.status).toBe('running');
		expect(store.buildId).toBe('build-1');

		second.emit('open');
		msg(second, {
			build_id: 'build-1',
			type: 'progress',
			progress: 0.5,
			elapsed_ms: 1000,
			estimated_remaining_ms: 1000,
			current_step: 'Running',
			current_step_index: 0,
			total_steps: 1
		});

		expect(store.status).toBe('running');
		expect(store.progress).toBe(0.5);
	});

	test('watch applies snapshot, event, error, and close callbacks', () => {
		const store = new BuildStreamStore();
		store.watch('build-3');

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		socket.emit('message', {
			data: JSON.stringify({
				type: 'snapshot',
				build: makeDetail({ build_id: 'build-3', progress: 0.2, current_step: 'Load' })
			})
		});
		msg(socket, {
			build_id: 'build-3',
			type: 'progress',
			progress: 0.6,
			elapsed_ms: 1500,
			estimated_remaining_ms: 500,
			current_step: 'Filter',
			current_step_index: 1,
			total_steps: 3
		});

		expect(store.buildId).toBe('build-3');
		expect(store.progress).toBe(0.6);
		expect(store.currentStep).toBe('Filter');

		socket.emit('error');
		expect(store.error).toBeNull();
		expect(store.status).toBe('running');

		store.watch('build-4');
		const next = MockWebSocket.instances[1];
		next.emit('close', { code: 1006, reason: 'Connection lost' });
		expect(store.status).toBe('connecting');
		expect(store.error).toBeNull();
		expect(mockRetainActivity).toHaveBeenCalledTimes(2);
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
		vi.advanceTimersByTime(1000);
		expect(MockWebSocket.instances).toHaveLength(3);
		expect(MockWebSocket.instances[2].url).toContain('/v1/compute/ws/builds/build-4');
	});

	test('applies snapshot', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		const snapshot: { type: string; build: ActiveBuildDetail } = {
			type: 'snapshot',
			build: {
				build_id: 'build-1',
				analysis_id: 'analysis-1',
				analysis_name: 'My Analysis',
				namespace: 'default',
				status: 'running',
				progress: 0.42,
				started_at: '2025-01-01T00:00:00Z',
				starter: STARTER,
				resource_config: null,
				elapsed_ms: 1200,
				estimated_remaining_ms: 800,
				current_step: 'Loading data',
				current_step_index: 0,
				total_steps: 3,
				current_kind: 'preview',
				current_datasource_id: 'ds-1',
				current_tab_id: 'tab-1',
				current_tab_name: 'Sheet 1',
				current_output_id: 'output-1',
				current_output_name: 'output_sheet_1',
				current_engine_run_id: 'run-1',
				total_tabs: 2,
				cancelled_at: null,
				cancelled_by: null,
				steps: [
					{
						build_step_index: 0,
						step_index: 0,
						step_id: 'step-load',
						step_name: 'Load',
						step_type: 'source',
						tab_id: null,
						tab_name: null,
						state: 'completed',
						duration_ms: 100,
						row_count: 500,
						error: null
					}
				],
				query_plans: [
					{
						tab_id: 'tab-1',
						tab_name: 'Sheet 1',
						optimized_plan: 'SCAN -> FILTER',
						unoptimized_plan: 'SCAN -> FILTER -> PROJECT'
					}
				],
				latest_resources: {
					sampled_at: '2025-01-01T00:00:01Z',
					cpu_percent: 55,
					memory_mb: 256,
					memory_limit_mb: 1024,
					active_threads: 2,
					max_threads: 8
				},
				resources: [],
				logs: [
					{
						timestamp: '2025-01-01T00:00:00Z',
						level: 'info',
						message: 'Started',
						step_name: null,
						step_id: null,
						tab_id: null,
						tab_name: null
					}
				],
				results: [],
				duration_ms: null,
				error: null,
				request_json: null,
				result_json: null
			}
		};
		socket.emit('message', { data: JSON.stringify(snapshot) });

		expect(store.buildId).toBe('build-1');
		expect(store.analysisId).toBe('analysis-1');
		expect(store.progress).toBe(0.42);
		expect(store.progressPct).toBe(42);
		expect(store.currentStep).toBe('Loading data');
		expect(store.totalSteps).toBe(3);
		expect(store.totalTabs).toBe(2);
		expect(store.steps).toHaveLength(1);
		expect(store.steps[0].state).toBe('completed');
		expect(store.steps[0].buildStepIndex).toBe(0);
		expect(store.steps[0].stepId).toBe('step-load');
		expect(store.steps[0].rowCount).toBe(500);
		expect(store.queryPlans).toHaveLength(1);
		expect(store.queryPlans[0].optimized).toBe('SCAN -> FILTER');
		expect(store.queryPlans[0].unoptimized).toBe('SCAN -> FILTER -> PROJECT');
		expect(store.logs).toHaveLength(1);
		expect(store.logs[0].level).toBe('info');
		expect(store.logs[0].message).toBe('Started');
		expect(store.latestResources).not.toBeNull();
		expect(store.latestResources!.cpu_percent).toBe(55);
		expect(store.status).toBe('running');
	});

	test('applies plan event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'plan',
			optimized_plan: 'SCAN -> FILTER -> PROJECT',
			unoptimized_plan: 'SCAN -> PROJECT -> FILTER'
		});

		expect(store.queryPlans).toHaveLength(1);
		expect(store.queryPlans[0].optimized).toBe('SCAN -> FILTER -> PROJECT');
		expect(store.queryPlans[0].unoptimized).toBe('SCAN -> PROJECT -> FILTER');
		expect(store.status).toBe('running');
	});

	test('upserts plan by tab identity', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'plan',
			tab_id: 'tab-1',
			tab_name: 'Sheet 1',
			optimized_plan: 'plan-v1',
			unoptimized_plan: 'unopt-v1'
		});
		msg(socket, {
			type: 'plan',
			tab_id: 'tab-2',
			tab_name: 'Sheet 2',
			optimized_plan: 'plan-tab2',
			unoptimized_plan: 'unopt-tab2'
		});

		expect(store.queryPlans).toHaveLength(2);

		msg(socket, {
			type: 'plan',
			tab_id: 'tab-1',
			tab_name: 'Sheet 1',
			optimized_plan: 'plan-v2',
			unoptimized_plan: 'unopt-v2'
		});

		expect(store.queryPlans).toHaveLength(2);
		const tab1 = store.queryPlans.find((p) => p.tabId === 'tab-1');
		expect(tab1!.optimized).toBe('plan-v2');
	});

	test('applies step_start event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'step_start',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-1',
			step_name: 'Load CSV',
			step_type: 'source',
			total_steps: 3,
			tab_id: 'tab-1',
			tab_name: 'Sheet 1'
		});

		expect(store.steps).toHaveLength(1);
		expect(store.steps[0].name).toBe('Load CSV');
		expect(store.steps[0].state).toBe('running');
		expect(store.steps[0].tabName).toBe('Sheet 1');
		expect(store.steps[0].buildStepIndex).toBe(0);
		expect(store.steps[0].stepId).toBe('step-1');
		expect(store.steps[0].stepType).toBe('source');
		expect(store.totalSteps).toBe(3);
	});

	test('applies step_complete event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'step_start',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-1',
			step_name: 'Load',
			step_type: 'source',
			total_steps: 3
		});
		msg(socket, {
			type: 'step_complete',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-1',
			step_name: 'Load',
			step_type: 'source',
			duration_ms: 350,
			row_count: 1000,
			total_steps: 3
		});

		expect(store.steps[0].state).toBe('completed');
		expect(store.steps[0].duration).toBe(350);
		expect(store.steps[0].rowCount).toBe(1000);
	});

	test('applies step_failed event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'step_failed',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-1',
			step_name: 'Transform',
			step_type: 'filter',
			error: 'column not found',
			total_steps: 3
		});

		expect(store.steps[0].state).toBe('failed');
		expect(store.steps[0].error).toBe('column not found');
	});

	test('applies progress event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'progress',
			progress: 0.65,
			elapsed_ms: 3200,
			estimated_remaining_ms: 1700,
			current_step: 'Filtering',
			current_step_index: 2,
			total_steps: 5
		});

		expect(store.progress).toBe(0.65);
		expect(store.progressPct).toBe(65);
		expect(store.elapsed).toBe(3200);
		expect(store.remaining).toBe(1700);
		expect(store.currentStep).toBe('Filtering');
		expect(store.currentStepIndex).toBe(2);
		expect(store.totalSteps).toBe(5);
	});

	test('progressPct clamps to 0-100', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'progress',
			progress: 1.0,
			elapsed_ms: 5000,
			estimated_remaining_ms: null,
			current_step: null,
			current_step_index: null,
			total_steps: 5
		});

		expect(store.progressPct).toBe(100);
	});

	test('applies resources event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'resources',
			cpu_percent: 78.5,
			memory_mb: 512,
			memory_limit_mb: 1024,
			active_threads: 4,
			max_threads: 8
		});

		expect(store.latestResources).not.toBeNull();
		expect(store.latestResources!.cpu_percent).toBe(78.5);
		expect(store.latestResources!.memory_mb).toBe(512);
		expect(store.latestResources!.memory_limit_mb).toBe(1024);
		expect(store.latestResources!.max_threads).toBe(8);
		expect(store.memoryPercent).toBe(50);
	});

	test('resources with null memory_limit_mb gives 0 memoryPercent', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'resources',
			cpu_percent: 50,
			memory_mb: 256,
			memory_limit_mb: null,
			active_threads: 2,
			max_threads: null
		});

		expect(store.latestResources).not.toBeNull();
		expect(store.latestResources!.memory_limit_mb).toBeNull();
		expect(store.latestResources!.max_threads).toBeNull();
		expect(store.memoryPercent).toBe(0);
	});

	test('applies log event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'log',
			message: 'test log message',
			level: 'warning',
			step_name: 'Load',
			step_id: 'step-1'
		});

		expect(store.logs).toHaveLength(1);
		expect(store.logs[0].level).toBe('warning');
		expect(store.logs[0].message).toBe('test log message');
		expect(store.logs[0].step_name).toBe('Load');
		expect(store.logs[0].step_id).toBe('step-1');
	});

	test('invalid websocket messages surface as protocol errors', () => {
		const store = new BuildStreamStore();
		store.watch('build-3');

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		socket.emit('message', { data: 'not-json' });

		expect(store.error).toBe('Invalid build stream message');
	});

	test('applies complete event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'complete',
			progress: 1.0,
			elapsed_ms: 5000,
			total_steps: 4,
			tabs_built: 2,
			results: [{ tab_id: 'tab-1', tab_name: 'Sheet 1', status: 'success' }],
			duration_ms: 4800
		});

		expect(store.status).toBe('completed');
		expect(store.progress).toBe(1.0);
		expect(store.progressPct).toBe(100);
		expect(store.duration).toBe(4800);
		expect(store.totalSteps).toBe(4);
		expect(store.results).toHaveLength(1);
		expect(store.done).toBe(true);
		expect(store.succeeded).toBe(true);
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('running snapshot with a step error does not mark the build failed', () => {
		mockStartSuccess(makeDetail({ status: 'running', error: 'step failed before terminal event' }));
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		expect(store.status).toBe('running');
		expect(store.error).toBe('step failed before terminal event');
		expect(store.done).toBe(false);
	});

	test('applies failed event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'failed',
			progress: 0.5,
			elapsed_ms: 3000,
			total_steps: 4,
			tabs_built: 1,
			results: [],
			duration_ms: 2800,
			error: 'Engine crashed'
		});

		expect(store.status).toBe('failed');
		expect(store.progress).toBe(0.5);
		expect(store.error).toBe('Engine crashed');
		expect(store.duration).toBe(2800);
		expect(store.done).toBe(true);
		expect(store.succeeded).toBe(false);
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('applies cancelled event', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'cancelled',
			progress: 0.4,
			elapsed_ms: 2100,
			total_steps: 4,
			tabs_built: 0,
			results: [],
			duration_ms: 2100,
			cancelled_at: '2026-04-10T11:00:00Z',
			cancelled_by: 'test@example.com'
		});

		expect(store.status).toBe('cancelled');
		expect(store.error).toBe('Cancelled by test@example.com');
		expect(store.done).toBe(true);
		expect(store.succeeded).toBe(false);
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('markCancelled keeps preview cancelled after late socket events', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'progress',
			progress: 0.4,
			elapsed_ms: 2100,
			estimated_remaining_ms: 1000,
			current_step: 'Loading data',
			current_step_index: 1,
			total_steps: 4
		});

		store.markCancelled({
			build_id: 'build-1',
			engine_run_id: 'run-1',
			status: 'cancelled',
			cancelled_at: '2026-04-10T11:00:00Z',
			cancelled_by: 'test@example.com',
			duration_ms: 2100
		});

		msg(socket, {
			type: 'progress',
			progress: 0.8,
			elapsed_ms: 5000,
			estimated_remaining_ms: 100,
			current_step: 'Still running',
			current_step_index: 3,
			total_steps: 4
		});

		expect(store.status).toBe('cancelled');
		expect(store.elapsed).toBe(2100);
		expect(store.error).toBe('Cancelled by test@example.com');
		expect(store.done).toBe(true);
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('reset clears all state', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'complete',
			progress: 1.0,
			elapsed_ms: 1000,
			total_steps: 1,
			tabs_built: 1,
			results: [{ tab_id: 't1', tab_name: 'Tab', status: 'success' }],
			duration_ms: 900
		});

		expect(store.done).toBe(true);

		store.reset();
		expect(store.status).toBe('disconnected');
		expect(store.buildId).toBeNull();
		expect(store.progress).toBe(0);
		expect(store.progressPct).toBe(0);
		expect(store.steps).toEqual([]);
		expect(store.logs).toEqual([]);
		expect(store.queryPlans).toEqual([]);
		expect(store.latestResources).toBeNull();
		expect(store.results).toEqual([]);
		expect(store.duration).toBeNull();
		expect(store.error).toBeNull();
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('updateStep sorts by buildStepIndex', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'step_start',
			build_step_index: 2,
			step_index: 0,
			step_id: 'step-c',
			step_name: 'Third step',
			step_type: 'transform',
			total_steps: 3
		});
		msg(socket, {
			type: 'step_start',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-a',
			step_name: 'First step',
			step_type: 'source',
			total_steps: 3
		});

		expect(store.steps).toHaveLength(2);
		expect(store.steps[0].buildStepIndex).toBe(0);
		expect(store.steps[0].name).toBe('First step');
		expect(store.steps[1].buildStepIndex).toBe(2);
		expect(store.steps[1].name).toBe('Third step');
	});

	test('updateStep replaces existing by buildStepIndex', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'step_start',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-1',
			step_name: 'Load',
			step_type: 'source',
			total_steps: 2
		});

		expect(store.steps[0].state).toBe('running');

		msg(socket, {
			type: 'step_complete',
			build_step_index: 0,
			step_index: 0,
			step_id: 'step-1',
			step_name: 'Load',
			step_type: 'source',
			duration_ms: 200,
			row_count: null,
			total_steps: 2
		});

		expect(store.steps).toHaveLength(1);
		expect(store.steps[0].state).toBe('completed');
		expect(store.steps[0].duration).toBe(200);
	});

	test('reconnects after unexpected close during live build', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		socket.emit('close', { code: 1006, reason: 'Connection lost' });

		expect(store.status).toBe('running');
		expect(store.error).toBeNull();
		vi.advanceTimersByTime(1000);
		expect(MockWebSocket.instances).toHaveLength(2);
		expect(MockWebSocket.instances[1].url).toContain('/v1/compute/ws/builds/build-1');
	});

	test('surfaces HTTP build-start failures', () => {
		mockStartError('Build start failed');
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		expect(store.status).toBe('disconnected');
		expect(store.error).toBe('Build start failed');
	});

	test('does not change status on close after completed', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'complete',
			progress: 1.0,
			elapsed_ms: 1000,
			total_steps: 1,
			tabs_built: 1,
			results: [],
			duration_ms: 900
		});

		socket.emit('close', { code: 1000, reason: '' });
		expect(store.status).toBe('completed');
		vi.advanceTimersByTime(1000);
		expect(MockWebSocket.instances).toHaveLength(1);
	});

	test('close stops reconnect attempts', () => {
		const store = new BuildStreamStore();
		store.watch('build-9');

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		socket.emit('close', { code: 1006, reason: 'Connection lost' });

		store.close();
		vi.advanceTimersByTime(1000);
		expect(MockWebSocket.instances).toHaveLength(1);
		expect(store.status).toBe('disconnected');
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('delays connection errors until reconnect attempts are exhausted', () => {
		const store = new BuildStreamStore();
		store.watch('build-9');

		const socket = MockWebSocket.instances[0];
		socket.emit('error');
		expect(store.error).toBeNull();

		for (let attempt = 0; attempt < 5; attempt++) {
			const current = MockWebSocket.instances.at(-1);
			if (!current) throw new Error('Expected websocket instance');
			current.emit('close', { code: 1006, reason: 'Connection lost' });
			expect(store.status).toBe('connecting');
			vi.advanceTimersByTime(1000);
		}

		const last = MockWebSocket.instances.at(-1);
		last?.emit('error');
		last?.emit('close', { code: 1006, reason: 'Connection lost' });

		expect(store.status).toBe('disconnected');
		expect(store.error).toBe('Connection lost');
		expect(mockReleaseActivity).toHaveBeenCalledTimes(1);
	});

	test('memoryPercent is 0 when no resources', () => {
		const store = new BuildStreamStore();
		expect(store.memoryPercent).toBe(0);
	});

	test('applySnapshot and applyEvent are callable directly', () => {
		const store = new BuildStreamStore();

		const detail: ActiveBuildDetail = {
			build_id: 'b-1',
			analysis_id: 'a-1',
			analysis_name: 'Direct',
			namespace: 'default',
			status: 'running',
			started_at: '2025-01-01T00:00:00Z',
			starter: STARTER,
			resource_config: null,
			progress: 0.1,
			elapsed_ms: 100,
			estimated_remaining_ms: 900,
			current_step: 'Loading',
			current_step_index: 0,
			total_steps: 2,
			current_kind: 'preview',
			current_datasource_id: 'ds-1',
			current_tab_id: null,
			current_tab_name: null,
			current_output_id: null,
			current_output_name: null,
			current_engine_run_id: null,
			total_tabs: 1,
			cancelled_at: null,
			cancelled_by: null,
			steps: [],
			query_plans: [],
			latest_resources: null,
			resources: [],
			logs: [],
			results: [],
			duration_ms: null,
			error: null,
			request_json: null,
			result_json: null
		};
		store.applySnapshot(detail);
		expect(store.buildId).toBe('b-1');
		expect(store.progress).toBe(0.1);
		expect(store.progressPct).toBe(10);

		store.applyEvent({
			type: 'progress',
			build_id: 'b-1',
			analysis_id: 'a-1',
			emitted_at: '2025-01-01T00:00:01Z',
			sequence: 1,
			current_kind: null,
			current_datasource_id: null,
			tab_id: null,
			tab_name: null,
			current_output_id: null,
			current_output_name: null,
			engine_run_id: null,
			progress: 0.5,
			elapsed_ms: 500,
			estimated_remaining_ms: 500,
			current_step: 'Filtering',
			current_step_index: 1,
			total_steps: 2
		});
		expect(store.progress).toBe(0.5);
		expect(store.progressPct).toBe(50);
	});

	test('resourceHistory accumulates from resource events', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'resources',
			cpu_percent: 50,
			memory_mb: 256,
			memory_limit_mb: 1024,
			active_threads: 2,
			max_threads: 8
		});
		msg(socket, {
			type: 'resources',
			cpu_percent: 75,
			memory_mb: 512,
			memory_limit_mb: 1024,
			active_threads: 4,
			max_threads: 8
		});

		expect(store.resourceHistory).toHaveLength(2);
		expect(store.resourceHistory[0].cpu_percent).toBe(50);
		expect(store.resourceHistory[1].cpu_percent).toBe(75);
		expect(store.latestResources!.cpu_percent).toBe(75);
	});

	test('applySnapshot populates resourceHistory and resourceConfig', () => {
		const store = new BuildStreamStore();

		const detail: ActiveBuildDetail = {
			build_id: 'b-2',
			analysis_id: 'a-2',
			analysis_name: 'Snapshot Test',
			namespace: 'default',
			status: 'running',
			started_at: '2025-01-01T00:00:00Z',
			starter: STARTER,
			resource_config: { max_threads: 4, max_memory_mb: 2048, streaming_chunk_size: 10000 },
			progress: 0.3,
			elapsed_ms: 300,
			estimated_remaining_ms: 700,
			current_step: 'Loading',
			current_step_index: 0,
			total_steps: 2,
			current_kind: 'preview',
			current_datasource_id: 'ds-2',
			current_tab_id: null,
			current_tab_name: null,
			current_output_id: null,
			current_output_name: null,
			current_engine_run_id: null,
			total_tabs: 1,
			cancelled_at: null,
			cancelled_by: null,
			steps: [],
			query_plans: [],
			latest_resources: {
				sampled_at: '2025-01-01T00:00:01Z',
				cpu_percent: 60,
				memory_mb: 512,
				memory_limit_mb: 2048,
				active_threads: 3,
				max_threads: 4
			},
			resources: [
				{
					sampled_at: '2025-01-01T00:00:01Z',
					cpu_percent: 60,
					memory_mb: 512,
					memory_limit_mb: 2048,
					active_threads: 3,
					max_threads: 4
				}
			],
			logs: [],
			results: [],
			duration_ms: null,
			error: null,
			request_json: null,
			result_json: null
		};

		store.applySnapshot(detail);
		expect(store.resourceConfig).not.toBeNull();
		expect(store.resourceConfig!.max_threads).toBe(4);
		expect(store.resourceConfig!.max_memory_mb).toBe(2048);
		expect(store.resourceConfig!.streaming_chunk_size).toBe(10000);
		expect(store.resourceHistory).toHaveLength(1);
		expect(store.resourceHistory[0].cpu_percent).toBe(60);
	});

	test('reset clears resourceHistory and resourceConfig', () => {
		const store = new BuildStreamStore();
		store.start(MINIMAL_BUILD_REQUEST);

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'resources',
			cpu_percent: 50,
			memory_mb: 256,
			memory_limit_mb: 1024,
			active_threads: 2,
			max_threads: 8
		});

		expect(store.resourceHistory).toHaveLength(1);
		store.reset();
		expect(store.resourceHistory).toEqual([]);
		expect(store.resourceConfig).toBeNull();
	});
});
