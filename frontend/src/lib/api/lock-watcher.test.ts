import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { watchLock } from './locks';

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'sig-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	getNamespace: () => 'default'
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

describe('watchLock', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	test('sends watch on open and forwards status updates', () => {
		const statuses: Array<{ owner_id: string } | null> = [];
		const watcher = watchLock({
			resourceType: 'analysis',
			resourceId: 'a-1',
			token: 'tok-1',
			onStatus: (lock) => statuses.push(lock ? { owner_id: lock.owner_id } : null)
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		const watchMsg = JSON.parse(socket.sent[0]);
		expect(watchMsg).toEqual({
			action: 'watch',
			resource_type: 'analysis',
			resource_id: 'a-1',
			lock_token: 'tok-1'
		});

		socket.emit('message', { data: JSON.stringify({ type: 'connected' }) });
		expect(statuses).toHaveLength(0);

		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-1',
				lock: { owner_id: 'client-1', lock_token: 'tok-1' }
			})
		});
		expect(statuses).toEqual([{ owner_id: 'client-1' }]);

		socket.emit('message', {
			data: JSON.stringify({
				type: 'status',
				resource_type: 'analysis',
				resource_id: 'a-1',
				lock: null
			})
		});
		expect(statuses).toEqual([{ owner_id: 'client-1' }, null]);

		watcher.close();
	});

	test('sends ping at configured interval', () => {
		const watcher = watchLock({
			resourceType: 'analysis',
			resourceId: 'a-2',
			token: 'tok-2',
			pingMs: 5_000,
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		expect(socket.sent).toHaveLength(1);

		vi.advanceTimersByTime(5_000);
		expect(socket.sent).toHaveLength(2);
		const ping = JSON.parse(socket.sent[1]);
		expect(ping).toEqual({ action: 'ping', lock_token: 'tok-2' });

		vi.advanceTimersByTime(5_000);
		expect(socket.sent).toHaveLength(3);

		watcher.close();
	});

	test('watch without token omits lock_token field', () => {
		const watcher = watchLock({
			resourceType: 'analysis',
			resourceId: 'a-3',
			token: null,
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');

		const watchMsg = JSON.parse(socket.sent[0]);
		expect(watchMsg).toEqual({
			action: 'watch',
			resource_type: 'analysis',
			resource_id: 'a-3'
		});

		vi.advanceTimersByTime(10_000);
		const ping = JSON.parse(socket.sent[1]);
		expect(ping).toEqual({ action: 'ping' });

		watcher.close();
	});

	test('close stops ping timer', () => {
		const watcher = watchLock({
			resourceType: 'analysis',
			resourceId: 'a-4',
			token: null,
			pingMs: 5_000,
			onStatus: () => {}
		});

		const socket = MockWebSocket.instances[0];
		socket.emit('open');
		expect(socket.sent).toHaveLength(1);

		watcher.close();
		vi.advanceTimersByTime(10_000);
		expect(socket.sent).toHaveLength(1);
	});
});
