import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { EngineRunsStreamStore } from './engine-runs-stream.svelte';
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

	send(message: string) {
		void message;
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

function makeRun(id: string, overrides: Partial<EngineRun> = {}): EngineRun {
	return {
		id,
		analysis_id: null,
		datasource_id: 'ds-1',
		kind: 'preview',
		status: 'success',
		request_json: {},
		result_json: null,
		error_message: null,
		created_at: '2025-01-01T00:00:00Z',
		completed_at: '2025-01-01T00:01:00Z',
		duration_ms: 1000,
		step_timings: {},
		query_plan: null,
		progress: 1,
		current_step: null,
		triggered_by: null,
		execution_entries: [],
		...overrides
	};
}

function sendMessage(socket: MockWebSocket, payload: Record<string, unknown>) {
	socket.emit('message', { data: JSON.stringify(payload) });
}

describe('EngineRunsStreamStore', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	test('initial state', () => {
		const store = new EngineRunsStreamStore();
		expect(store.runs).toEqual([]);
		expect(store.connected).toBe(false);
		expect(store.error).toBeNull();
	});

	test('connect opens websocket with params in URL', () => {
		const store = new EngineRunsStreamStore();
		store.connect({ kind: 'preview', limit: 50, offset: 0 });

		expect(MockWebSocket.instances).toHaveLength(1);
		const url = new URL(MockWebSocket.instances[0].url);
		expect(url.pathname).toContain('/v1/engine-runs/ws');
		expect(url.searchParams.get('kind')).toBe('preview');
		expect(url.searchParams.get('limit')).toBe('50');
		expect(url.searchParams.get('offset')).toBe('0');
	});

	test('applies snapshot', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		const runs = [makeRun('run-1'), makeRun('run-2')];
		sendMessage(socket, { type: 'snapshot', runs });

		expect(store.runs).toHaveLength(2);
		expect(store.runs[0].id).toBe('run-1');
		expect(store.runs[1].id).toBe('run-2');
		expect(store.connected).toBe(true);
	});

	test('applies update for existing run', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		sendMessage(socket, { type: 'snapshot', runs: [makeRun('run-1', { status: 'running' })] });

		expect(store.runs[0].status).toBe('running');

		sendMessage(socket, { type: 'update', run: makeRun('run-1', { status: 'success' }) });

		expect(store.runs).toHaveLength(1);
		expect(store.runs[0].status).toBe('success');
	});

	test('applies update for new run sorted by created_at descending', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		sendMessage(socket, {
			type: 'snapshot',
			runs: [makeRun('run-1', { created_at: '2025-01-01T00:02:00Z' })]
		});
		sendMessage(socket, {
			type: 'update',
			run: makeRun('run-2', { created_at: '2025-01-01T00:03:00Z' })
		});

		expect(store.runs).toHaveLength(2);
		expect(store.runs[0].id).toBe('run-2');
		expect(store.runs[1].id).toBe('run-1');
	});

	test('sorts new runs by created_at even when arriving out of order', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		sendMessage(socket, {
			type: 'snapshot',
			runs: [makeRun('run-1', { created_at: '2025-01-01T00:03:00Z' })]
		});
		sendMessage(socket, {
			type: 'update',
			run: makeRun('run-2', { created_at: '2025-01-01T00:01:00Z' })
		});

		expect(store.runs).toHaveLength(2);
		expect(store.runs[0].id).toBe('run-1');
		expect(store.runs[1].id).toBe('run-2');
	});

	test('sets error on websocket error', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		socket.emit('error');

		expect(store.error).toBe('WebSocket connection failed');
	});

	test('sets error on unexpected close', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		socket.emit('close', { code: 1006, reason: 'Connection lost' });

		expect(store.error).toBe('Connection lost');
		expect(store.connected).toBe(false);
	});

	test('normal close does not set error', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		sendMessage(socket, { type: 'snapshot', runs: [] });
		socket.emit('close', { code: 1000, reason: '' });

		expect(store.error).toBeNull();
		expect(store.connected).toBe(false);
	});

	test('disconnect closes connection', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		expect(MockWebSocket.instances).toHaveLength(1);
		store.disconnect();
		expect(store.connected).toBe(false);
	});

	test('reconnect closes previous connection', () => {
		const store = new EngineRunsStreamStore();
		store.connect({ kind: 'preview' });
		store.connect({ kind: 'download' });

		expect(MockWebSocket.instances).toHaveLength(2);
	});

	test('times out if no snapshot arrives', () => {
		vi.useFakeTimers();
		const store = new EngineRunsStreamStore();
		store.connect({});

		expect(store.connected).toBe(false);
		expect(store.error).toBeNull();

		vi.advanceTimersByTime(10_000);

		expect(store.error).toBe('Timed out waiting for engine runs snapshot');
		expect(store.connected).toBe(false);
	});

	test('timeout is cleared when snapshot arrives', () => {
		vi.useFakeTimers();
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		sendMessage(socket, { type: 'snapshot', runs: [] });

		vi.advanceTimersByTime(10_000);

		expect(store.error).toBeNull();
		expect(store.connected).toBe(true);
	});

	test('ignores malformed messages', () => {
		const store = new EngineRunsStreamStore();
		store.connect({});

		const socket = MockWebSocket.instances[0];
		socket.emit('message', { data: 'not json' });

		expect(store.runs).toEqual([]);
		expect(store.error).toBeNull();
	});
});
