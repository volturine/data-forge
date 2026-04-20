import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createStream } from './websocket';

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true
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

type TestSnapshot = { items: string[] };
type TestSnapshotMessage = { type: 'snapshot'; items: string[] };
type TestEvent = { type: 'action'; action: string };
type TestError = { type: 'error'; error: string };
type TestMessage = TestSnapshotMessage | TestEvent | TestError;

function parse(data: string): TestMessage | null {
	try {
		return JSON.parse(data) as TestMessage;
	} catch {
		return null;
	}
}

function isSnapshot(msg: TestMessage): msg is TestSnapshotMessage {
	return msg.type === 'snapshot';
}

function extractSnapshot(msg: TestMessage): TestSnapshot {
	if (!isSnapshot(msg)) {
		throw new Error('Expected snapshot');
	}
	return { items: msg.items };
}

function extractEvent(msg: TestMessage): TestEvent {
	if (msg.type !== 'action') {
		throw new Error('Expected event');
	}
	return msg;
}

describe('createStream', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function connect(
		overrides: {
			onSnapshot?: (snapshot: TestSnapshot) => void;
			onEvent?: (event: TestEvent) => void;
			onError?: (error: string) => void;
			onClose?: () => void;
		} = {}
	) {
		const callbacks = {
			onSnapshot: overrides.onSnapshot ?? vi.fn(),
			onEvent: overrides.onEvent ?? vi.fn(),
			onError: overrides.onError ?? vi.fn(),
			onClose: overrides.onClose ?? vi.fn()
		};
		const handle = createStream<TestSnapshot, TestEvent, TestMessage>('/v1/test/ws', {
			parse,
			isSnapshot,
			extractSnapshot,
			extractEvent,
			callbacks
		});
		const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
		return { handle, callbacks, socket };
	}

	test('creates WebSocket with correct URL', () => {
		connect();
		expect(MockWebSocket.instances).toHaveLength(1);
		expect(MockWebSocket.instances[0].url).toContain('/v1/test/ws');
	});

	test('dispatches snapshot messages', () => {
		const onSnapshot = vi.fn();
		const { socket } = connect({ onSnapshot });
		const data = { type: 'snapshot', items: ['a', 'b'] };
		socket.emit('message', { data: JSON.stringify(data) });
		expect(onSnapshot).toHaveBeenCalledOnce();
	});

	test('dispatches event messages', () => {
		const onEvent = vi.fn();
		const { socket } = connect({ onEvent });
		socket.emit('message', { data: JSON.stringify({ type: 'action', action: 'do-thing' }) });
		expect(onEvent).toHaveBeenCalledOnce();
	});

	test('dispatches error-type messages via onError', () => {
		const onError = vi.fn();
		const { socket } = connect({ onError });
		socket.emit('message', { data: JSON.stringify({ type: 'error', error: 'bad request' }) });
		expect(onError).toHaveBeenCalledWith('bad request');
	});

	test('ignores invalid JSON', () => {
		const onSnapshot = vi.fn();
		const onError = vi.fn();
		const { socket } = connect({ onSnapshot, onError });
		socket.emit('message', { data: 'not-json' });
		expect(onSnapshot).not.toHaveBeenCalled();
		expect(onError).not.toHaveBeenCalled();
	});

	test('WebSocket error event calls onError', () => {
		const onError = vi.fn();
		const { socket } = connect({ onError });
		socket.emit('error');
		expect(onError).toHaveBeenCalledWith('WebSocket connection failed');
	});

	test('normal close (1000) calls onClose without onError', () => {
		const onError = vi.fn();
		const onClose = vi.fn();
		const { socket } = connect({ onError, onClose });
		socket.emit('close', { code: 1000, reason: '' });
		expect(onError).not.toHaveBeenCalled();
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('code 1005 close does not call onError', () => {
		const onError = vi.fn();
		const onClose = vi.fn();
		const { socket } = connect({ onError, onClose });
		socket.emit('close', { code: 1005, reason: '' });
		expect(onError).not.toHaveBeenCalled();
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('abnormal close calls onError then onClose', () => {
		const onError = vi.fn();
		const onClose = vi.fn();
		const { socket } = connect({ onError, onClose });
		socket.emit('close', { code: 1006, reason: 'Connection lost' });
		expect(onError).toHaveBeenCalledWith('Connection lost');
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('abnormal close without reason uses fallback message', () => {
		const onError = vi.fn();
		const { socket } = connect({ onError });
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

	test('snapshot-only stream without onEvent', () => {
		const onSnapshot = vi.fn();
		const callbacks = {
			onSnapshot,
			onError: vi.fn(),
			onClose: vi.fn()
		};
		createStream<TestSnapshot, never, TestMessage>('/v1/test/ws', {
			parse,
			isSnapshot,
			extractSnapshot: extractSnapshot,
			callbacks
		});
		const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
		socket.emit('message', { data: JSON.stringify({ type: 'snapshot', items: ['x'] }) });
		expect(onSnapshot).toHaveBeenCalledOnce();
	});
});
