import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { EngineRunsStore } from './engine-runs.svelte';
import type { EngineRun } from '$lib/api/engine-runs';

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

	close(_code?: number) {
		this.readyState = 3;
		this.emit('close', { code: 1000, reason: '' });
	}

	emit(type: string, event?: { data?: string; code?: number; reason?: string }) {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event);
		}
	}
}

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

function sendSnapshot(socket: MockWebSocket, runs: EngineRun[]) {
	socket.emit('message', { data: JSON.stringify({ type: 'snapshot', runs }) });
}

function sendError(socket: MockWebSocket, error: string) {
	socket.emit('message', { data: JSON.stringify({ type: 'error', error }) });
}

describe('EngineRunsStore', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	test('initial state', () => {
		const store = new EngineRunsStore();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});

	test('start sets status to connecting', () => {
		const store = new EngineRunsStore();
		store.start({ datasource_id: 'ds-1', limit: 50 });
		expect(store.status).toBe('connecting');
		expect(MockWebSocket.instances).toHaveLength(1);
	});

	test('snapshot sets runs and status to connected', () => {
		const store = new EngineRunsStore();
		store.start();
		const socket = MockWebSocket.instances[0];
		const runs = [makeRun(), makeRun({ id: 'run-2' })];
		sendSnapshot(socket, runs);
		expect(store.runs).toEqual(runs);
		expect(store.status).toBe('connected');
		expect(store.error).toBeNull();
	});

	test('error message sets error and status', () => {
		const store = new EngineRunsStore();
		store.start();
		const socket = MockWebSocket.instances[0];
		sendError(socket, 'Permission denied');
		expect(store.error).toBe('Permission denied');
		expect(store.status).toBe('error');
	});

	test('close after error keeps error status', () => {
		const store = new EngineRunsStore();
		store.start();
		const socket = MockWebSocket.instances[0];
		sendError(socket, 'Timeout');
		expect(store.status).toBe('error');
		socket.emit('close', { code: 1000, reason: '' });
		expect(store.status).toBe('error');
	});

	test('normal close sets disconnected when no error', () => {
		const store = new EngineRunsStore();
		store.start();
		const socket = MockWebSocket.instances[0];
		sendSnapshot(socket, [makeRun()]);
		expect(store.status).toBe('connected');
		socket.emit('close', { code: 1000, reason: '' });
		expect(store.status).toBe('disconnected');
	});

	test('close() method disconnects', () => {
		const store = new EngineRunsStore();
		store.start();
		expect(MockWebSocket.instances).toHaveLength(1);
		store.close();
		expect(MockWebSocket.instances[0].readyState).toBe(3);
	});

	test('close() when not connected is safe', () => {
		const store = new EngineRunsStore();
		expect(() => store.close()).not.toThrow();
	});

	test('reset clears all state', () => {
		const store = new EngineRunsStore();
		store.start();
		const socket = MockWebSocket.instances[0];
		sendSnapshot(socket, [makeRun()]);
		expect(store.runs).toHaveLength(1);
		store.reset();
		expect(store.runs).toEqual([]);
		expect(store.status).toBe('disconnected');
		expect(store.error).toBeNull();
	});

	test('start closes previous connection', () => {
		const store = new EngineRunsStore();
		store.start({ datasource_id: 'ds-1' });
		expect(MockWebSocket.instances).toHaveLength(1);
		const first = MockWebSocket.instances[0];
		store.start({ datasource_id: 'ds-2' });
		expect(MockWebSocket.instances).toHaveLength(2);
		expect(first.readyState).toBe(3);
	});

	test('start clears previous error', () => {
		const store = new EngineRunsStore();
		store.start();
		sendError(MockWebSocket.instances[0], 'fail');
		expect(store.error).toBe('fail');
		store.start();
		expect(store.error).toBeNull();
		expect(store.status).toBe('connecting');
	});

	test('snapshot after error clears error', () => {
		const store = new EngineRunsStore();
		store.start();
		const socket = MockWebSocket.instances[0];
		sendError(socket, 'temporary');
		expect(store.status).toBe('error');
		sendSnapshot(socket, [makeRun()]);
		expect(store.status).toBe('connected');
		expect(store.error).toBeNull();
	});

	test('filter params are passed to WebSocket URL', () => {
		const store = new EngineRunsStore();
		store.start({ datasource_id: 'ds-42', limit: 25 });
		const socket = MockWebSocket.instances[0];
		expect(socket.url).toContain('datasource_id=ds-42');
		expect(socket.url).toContain('limit=25');
	});
});
