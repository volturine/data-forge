import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { openLockSession } from './locks';

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true
}));

type Listener = (event?: { data?: string; code?: number; reason?: string }) => void;

class MockWebSocket {
	static OPEN = 1;
	static instances: MockWebSocket[] = [];

	url: string;
	readyState = MockWebSocket.OPEN;
	sent: string[] = [];
	private listeners = new Map<string, Listener[]>();

	constructor(url: string) {
		this.url = url;
		MockWebSocket.instances.push(this);
	}

	addEventListener(type: string, listener: Listener) {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	send(message: string) {
		this.sent.push(message);
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

describe('openLockSession', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	test('sends watch on open, acquires ownership, and releases with the owned token', () => {
		const statuses: Array<{ owner_id: string; ownsLock: boolean } | null> = [];
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-1',
			onStatus: (lock, ownsLock) => {
				if (!lock) {
					statuses.push(null);
					return;
				}
				statuses.push({ owner_id: lock.owner_id, ownsLock });
			}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		expect(JSON.parse(socket.sent[0])).toEqual({
			action: 'watch',
			resource_type: 'analysis',
			resource_id: 'a-1'
		});

		socket.emit('message', { data: JSON.stringify({ type: 'connected' }) });
		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-1',
				lock: null
			})
		});
		expect(statuses).toEqual([null]);

		session.acquire();
		expect(JSON.parse(socket.sent[1])).toEqual({ action: 'acquire' });

		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-1',
				lock: { owner_id: 'client-1', lock_token: 'tok-1' }
			})
		});
		expect(statuses).toEqual([null, { owner_id: 'client-1', ownsLock: true }]);

		session.release();
		expect(JSON.parse(socket.sent[2])).toEqual({ action: 'release', lock_token: 'tok-1' });

		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-1',
				lock: null
			})
		});
		expect(statuses).toEqual([null, { owner_id: 'client-1', ownsLock: true }, null]);

		session.close();
	});

	test('pings with the owned token after a successful acquire', () => {
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-2',
			pingMs: 5_000,
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		session.acquire();
		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-2',
				lock: { owner_id: 'client-1', lock_token: 'tok-2' }
			})
		});

		vi.advanceTimersByTime(5_000);
		expect(JSON.parse(socket.sent[2])).toEqual({ action: 'ping', lock_token: 'tok-2' });

		session.close();
	});

	test('pings without a token before ownership is acquired', () => {
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-3',
			pingMs: 5_000,
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		vi.advanceTimersByTime(5_000);
		expect(JSON.parse(socket.sent[1])).toEqual({ action: 'ping' });

		session.close();
	});

	test('forwards websocket errors with status codes', () => {
		const errors: Array<{ error: string; statusCode: number }> = [];
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-4',
			onStatus: () => {},
			onError: (error) => errors.push(error)
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		socket.emit('message', {
			data: JSON.stringify({
				type: 'error',
				error: 'analysis a-4 is locked by another owner',
				status_code: 409
			})
		});

		expect(errors).toEqual([{ error: 'analysis a-4 is locked by another owner', statusCode: 409 }]);

		session.close();
	});

	test('close stops ping timer', () => {
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-5',
			pingMs: 5_000,
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		expect(socket.sent).toHaveLength(1);

		session.close();
		vi.advanceTimersByTime(10_000);
		expect(socket.sent).toHaveLength(1);
	});

	test('reconnects and re-watches after a transient close', () => {
		const statuses: Array<{ ownsLock: boolean } | null> = [];
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-6',
			onStatus: (lock, ownsLock) => {
				if (!lock) {
					statuses.push(null);
					return;
				}
				statuses.push({ ownsLock });
			}
		});

		const first = MockWebSocket.instances[0];
		first.emit('open');
		expect(JSON.parse(first.sent[0])).toEqual({
			action: 'watch',
			resource_type: 'analysis',
			resource_id: 'a-6'
		});

		first.emit('close', { code: 1006, reason: 'Connection lost' });
		expect(statuses).toEqual([null]);

		vi.advanceTimersByTime(1_000);
		expect(MockWebSocket.instances).toHaveLength(2);

		const second = MockWebSocket.instances[1];
		second.emit('open');
		expect(JSON.parse(second.sent[0])).toEqual({
			action: 'watch',
			resource_type: 'analysis',
			resource_id: 'a-6'
		});

		session.close();
	});

	test('manual close prevents reconnect after socket close', () => {
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-7',
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		session.close();
		vi.advanceTimersByTime(1_000);
		expect(MockWebSocket.instances).toHaveLength(1);
	});

	test('retries acquire after watch reports no lock', () => {
		const session = openLockSession({
			resourceType: 'analysis',
			resourceId: 'a-8',
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		session.acquire();
		expect(JSON.parse(socket.sent[1])).toEqual({ action: 'acquire' });

		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-8',
				lock: null
			})
		});

		expect(JSON.parse(socket.sent[2])).toEqual({ action: 'acquire' });
		session.close();
	});
});
