import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { connectEngineRunsStream } from './engine-runs';
import type { EngineRunsStreamCallbacks, EngineRun } from './engine-runs';

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

describe('connectEngineRunsStream', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function connect(
		params?: Parameters<typeof connectEngineRunsStream>[0],
		overrides: Partial<EngineRunsStreamCallbacks> = {}
	) {
		const callbacks: EngineRunsStreamCallbacks = {
			onSnapshot: overrides.onSnapshot ?? vi.fn(),
			onError: overrides.onError ?? vi.fn(),
			onClose: overrides.onClose ?? vi.fn()
		};
		const handle = connectEngineRunsStream(params, callbacks);
		return {
			handle,
			callbacks,
			socket: MockWebSocket.instances[MockWebSocket.instances.length - 1]
		};
	}

	test('creates WebSocket connection', () => {
		connect();
		expect(MockWebSocket.instances).toHaveLength(1);
	});

	test('includes filter params in URL', () => {
		connect({ datasource_id: 'ds-42', limit: 50 });
		const socket = MockWebSocket.instances[0];
		expect(socket.url).toContain('datasource_id=ds-42');
		expect(socket.url).toContain('limit=50');
	});

	test('includes all filter params', () => {
		connect({ analysis_id: 'a-1', kind: 'datasource_update', status: 'success', offset: 10 });
		const socket = MockWebSocket.instances[0];
		expect(socket.url).toContain('analysis_id=a-1');
		expect(socket.url).toContain('kind=datasource_update');
		expect(socket.url).toContain('status=success');
		expect(socket.url).toContain('offset=10');
	});

	test('no params produces clean endpoint', () => {
		connect();
		const socket = MockWebSocket.instances[0];
		expect(socket.url).toContain('/v1/engine-runs/ws');
		expect(socket.url).not.toContain('datasource_id');
	});

	test('snapshot message calls onSnapshot', () => {
		const onSnapshot = vi.fn();
		const { socket } = connect(undefined, { onSnapshot });
		const runs = [makeRun()];
		socket.emit('message', { data: JSON.stringify({ type: 'snapshot', runs }) });
		expect(onSnapshot).toHaveBeenCalledOnce();
		expect(onSnapshot).toHaveBeenCalledWith(runs);
	});

	test('error message calls onError', () => {
		const onError = vi.fn();
		const { socket } = connect(undefined, { onError });
		socket.emit('message', { data: JSON.stringify({ type: 'error', error: 'Bad request' }) });
		expect(onError).toHaveBeenCalledWith('Bad request');
	});

	test('invalid JSON is ignored', () => {
		const onSnapshot = vi.fn();
		const onError = vi.fn();
		const { socket } = connect(undefined, { onSnapshot, onError });
		socket.emit('message', { data: 'not-json' });
		expect(onSnapshot).not.toHaveBeenCalled();
		expect(onError).not.toHaveBeenCalled();
	});

	test('WebSocket error event calls onError', () => {
		const onError = vi.fn();
		const { socket } = connect(undefined, { onError });
		socket.emit('error');
		expect(onError).toHaveBeenCalledWith('WebSocket connection failed');
	});

	test('normal close calls onClose without error', () => {
		const onError = vi.fn();
		const onClose = vi.fn();
		const { socket } = connect(undefined, { onError, onClose });
		socket.emit('close', { code: 1000, reason: '' });
		expect(onError).not.toHaveBeenCalled();
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('code 1005 close does not call onError', () => {
		const onError = vi.fn();
		const onClose = vi.fn();
		const { socket } = connect(undefined, { onError, onClose });
		socket.emit('close', { code: 1005, reason: '' });
		expect(onError).not.toHaveBeenCalled();
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('abnormal close calls onError then onClose', () => {
		const onError = vi.fn();
		const onClose = vi.fn();
		const { socket } = connect(undefined, { onError, onClose });
		socket.emit('close', { code: 1006, reason: 'Connection lost' });
		expect(onError).toHaveBeenCalledWith('Connection lost');
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('abnormal close without reason uses fallback message', () => {
		const onError = vi.fn();
		const { socket } = connect(undefined, { onError });
		socket.emit('close', { code: 1006, reason: '' });
		expect(onError).toHaveBeenCalledWith('Connection closed (code 1006)');
	});

	test('close() on handle closes socket', () => {
		const { handle, socket } = connect();
		expect(socket.readyState).toBe(1);
		handle.close();
		expect(socket.readyState).toBe(3);
	});

	test('close() on already-closed socket is safe', () => {
		const { handle, socket } = connect();
		socket.readyState = 3;
		expect(() => handle.close()).not.toThrow();
	});
});
