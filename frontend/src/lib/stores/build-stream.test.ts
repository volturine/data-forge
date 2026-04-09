import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { BuildStreamStore } from './build-stream.svelte';
import type { ActiveBuildDetail } from '$lib/types/build-stream';

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	getNamespace: () => 'default'
}));

type Listener = (event?: { data?: string; code?: number; reason?: string }) => void;

class MockWebSocket {
	static instances: MockWebSocket[] = [];

	url: string;
	sentMessages: string[] = [];
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

	send(message: string) {
		this.sentMessages.push(message);
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

describe('BuildStreamStore', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
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

	test('start sends request and connects', () => {
		const store = new BuildStreamStore();
		store.start({ analysis_pipeline: { tabs: [] }, tab_id: null });

		expect(MockWebSocket.instances).toHaveLength(1);
		const socket = MockWebSocket.instances[0];

		socket.emit('open');
		expect(socket.sentMessages).toHaveLength(1);
		expect(JSON.parse(socket.sentMessages[0])).toEqual({
			analysis_pipeline: { tabs: [] },
			tab_id: null
		});
	});

	test('applies snapshot', () => {
		const store = new BuildStreamStore();
		store.start({ analysis_pipeline: { tabs: [] } });

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
				current_tab_id: 'tab-1',
				current_tab_name: 'Sheet 1',
				current_output_id: 'output-1',
				current_output_name: 'output_sheet_1',
				total_tabs: 2,
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
				error: null
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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

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
		store.start({});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		msg(socket, {
			type: 'log',
			message: 'test log message',
			level: 'warn',
			step_name: 'Load',
			step_id: 'step-1'
		});

		expect(store.logs).toHaveLength(1);
		expect(store.logs[0].level).toBe('warn');
		expect(store.logs[0].message).toBe('test log message');
		expect(store.logs[0].step_name).toBe('Load');
		expect(store.logs[0].step_id).toBe('step-1');
	});

	test('applies complete event', () => {
		const store = new BuildStreamStore();
		store.start({});

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
	});

	test('applies failed event', () => {
		const store = new BuildStreamStore();
		store.start({});

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
	});

	test('reset clears all state', () => {
		const store = new BuildStreamStore();
		store.start({});

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
	});

	test('updateStep sorts by buildStepIndex', () => {
		const store = new BuildStreamStore();
		store.start({});

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
		store.start({});

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

	test('disconnected status on unexpected close', () => {
		const store = new BuildStreamStore();
		store.start({});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		socket.emit('close', { code: 1006, reason: 'Connection lost' });

		expect(store.status).toBe('disconnected');
	});

	test('times out if no snapshot or event arrives after start', () => {
		vi.useFakeTimers();
		const store = new BuildStreamStore();
		store.start({});

		expect(store.status).toBe('connecting');

		vi.advanceTimersByTime(10_000);

		expect(store.status).toBe('disconnected');
		expect(store.error).toBe('Timed out waiting for build updates');
	});

	test('does not change status on close after completed', () => {
		const store = new BuildStreamStore();
		store.start({});

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
			current_tab_id: null,
			current_tab_name: null,
			current_output_id: null,
			current_output_name: null,
			total_tabs: 1,
			steps: [],
			query_plans: [],
			latest_resources: null,
			resources: [],
			logs: [],
			results: [],
			duration_ms: null,
			error: null
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
		store.start({});

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
			current_tab_id: null,
			current_tab_name: null,
			current_output_id: null,
			current_output_name: null,
			total_tabs: 1,
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
			error: null
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
		store.start({});

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
