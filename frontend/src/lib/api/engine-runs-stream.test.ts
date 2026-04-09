import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { connectEngineRunsStream } from './engine-runs-stream';
import type { EngineRun } from './engine-runs';

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

function makeRun(id: string): EngineRun {
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
		execution_entries: []
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

	test('builds websocket URL with filter params', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({ kind: 'preview', limit: 50, offset: 10 }, callbacks);

		expect(MockWebSocket.instances).toHaveLength(1);
		const url = new URL(MockWebSocket.instances[0].url);
		expect(url.pathname).toContain('/v1/engine-runs/ws');
		expect(url.searchParams.get('kind')).toBe('preview');
		expect(url.searchParams.get('limit')).toBe('50');
		expect(url.searchParams.get('offset')).toBe('10');
	});

	test('calls onSnapshot for snapshot messages', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({}, callbacks);

		const socket = MockWebSocket.instances[0];
		const runs = [makeRun('run-1')];
		socket.emit('message', { data: JSON.stringify({ type: 'snapshot', runs }) });

		expect(callbacks.onSnapshot).toHaveBeenCalledWith(runs);
	});

	test('calls onUpdate for update messages', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({}, callbacks);

		const socket = MockWebSocket.instances[0];
		const run = makeRun('run-1');
		socket.emit('message', { data: JSON.stringify({ type: 'update', run }) });

		expect(callbacks.onUpdate).toHaveBeenCalledWith(run);
	});

	test('calls onError on websocket error', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({}, callbacks);

		const socket = MockWebSocket.instances[0];
		socket.emit('error');

		expect(callbacks.onError).toHaveBeenCalledWith('WebSocket connection failed');
	});

	test('calls onError and onClose on unexpected close', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({}, callbacks);

		const socket = MockWebSocket.instances[0];
		socket.emit('close', { code: 1006, reason: 'Connection lost' });

		expect(callbacks.onError).toHaveBeenCalledWith('Connection lost');
		expect(callbacks.onClose).toHaveBeenCalled();
	});

	test('close method closes the socket', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		const conn = connectEngineRunsStream({}, callbacks);

		conn.close();
		expect(callbacks.onClose).toHaveBeenCalled();
	});

	test('ignores malformed messages', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({}, callbacks);

		const socket = MockWebSocket.instances[0];
		socket.emit('message', { data: 'not json' });

		expect(callbacks.onSnapshot).not.toHaveBeenCalled();
		expect(callbacks.onUpdate).not.toHaveBeenCalled();
	});

	test('no params produces URL without query string', () => {
		const callbacks = {
			onSnapshot: vi.fn(),
			onUpdate: vi.fn(),
			onError: vi.fn(),
			onClose: vi.fn()
		};
		connectEngineRunsStream({}, callbacks);

		const url = new URL(MockWebSocket.instances[0].url);
		expect(url.searchParams.has('kind')).toBe(false);
		expect(url.searchParams.has('status')).toBe(false);
		expect(url.searchParams.has('limit')).toBe(false);
	});
});
