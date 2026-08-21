import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { LockSession, LockStatus } from './locks';

type Listener = (event?: { data?: string }) => void;

class MockWebSocket {
	readyState = 1;
	sent: string[] = [];
	closed = false;
	private listeners = new Map<string, Listener[]>();

	addEventListener(type: string, listener: Listener) {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	send(message: string) {
		this.sent.push(message);
	}

	close() {
		this.closed = true;
		this.readyState = 3;
	}

	emit(type: string, event?: { data?: string }) {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event);
		}
	}
}

const sockets: MockWebSocket[] = [];

vi.mock('./websocket', () => ({
	preferHttp: () => false,
	createOwnedWebSocket: () => {
		const socket = new MockWebSocket();
		sockets.push(socket);
		return socket as unknown as WebSocket;
	},
	closeOwnedWebSocket: (socket: MockWebSocket) => {
		socket.close();
	}
}));

function sentMessages(socket: MockWebSocket): Array<Record<string, unknown>> {
	return socket.sent.map((message) => JSON.parse(message) as Record<string, unknown>);
}

function statusMessage(lock: LockStatus | null): string {
	return JSON.stringify({
		type: 'status',
		resource_type: 'analysis',
		resource_id: 'analysis-1',
		lock
	});
}

function lock(lockToken: string): LockStatus {
	return {
		resource_type: 'analysis',
		resource_id: 'analysis-1',
		owner_id: 'user-1',
		lock_token: lockToken,
		acquired_at: '2024-01-01T00:00:00Z',
		expires_at: '2024-01-01T00:00:30Z',
		last_heartbeat: '2024-01-01T00:00:00Z',
		is_expired: false
	};
}

describe('openLockSession', () => {
	let openLockSession: typeof import('./locks').openLockSession;

	beforeEach(async () => {
		sockets.length = 0;
		vi.resetModules();
		({ openLockSession } = await import('./locks'));
	});

	afterEach(() => {
		for (const socket of sockets) {
			if (!socket.closed) {
				socket.close();
			}
		}
		sockets.length = 0;
		vi.clearAllMocks();
		vi.useRealTimers();
	});

	test('reacquires when connect sees an existing lock before the first token is known', () => {
		const onStatus = vi.fn();
		const onError = vi.fn();
		const session: LockSession = openLockSession({
			resourceType: 'analysis',
			resourceId: 'analysis-1',
			onStatus,
			onError
		});
		const socket = sockets[0];
		session.acquire();
		socket.emit('open');
		socket.emit('message', { data: statusMessage(lock('existing-lock')) });

		expect(sentMessages(socket)).toEqual([
			{ action: 'watch', resource_type: 'analysis', resource_id: 'analysis-1' },
			{ action: 'acquire' }
		]);
		expect(onStatus).not.toHaveBeenCalledWith(
			expect.objectContaining({ lock_token: 'existing-lock' }),
			false
		);

		socket.emit('message', { data: statusMessage(lock('replacement-lock')) });

		expect(onError).not.toHaveBeenCalled();
		expect(onStatus).toHaveBeenLastCalledWith(
			expect.objectContaining({ lock_token: 'replacement-lock' }),
			true
		);
		session.close();
	});

	test('does not spam acquire on repeated existing-lock statuses after a 409 conflict', () => {
		const onStatus = vi.fn();
		const onError = vi.fn();
		const session: LockSession = openLockSession({
			resourceType: 'analysis',
			resourceId: 'analysis-1',
			onStatus,
			onError
		});
		const socket = sockets[0];
		session.acquire();
		socket.emit('open');
		socket.emit('message', { data: statusMessage(lock('other-lock')) });
		socket.emit('message', {
			data: JSON.stringify({ type: 'error', error: 'locked by another owner', status_code: 409 })
		});
		socket.emit('message', { data: statusMessage(lock('other-lock')) });

		expect(sentMessages(socket)).toEqual([
			{ action: 'watch', resource_type: 'analysis', resource_id: 'analysis-1' },
			{ action: 'acquire' }
		]);
		expect(onError).toHaveBeenCalledWith({ error: 'locked by another owner', statusCode: 409 });
		expect(onStatus).toHaveBeenLastCalledWith(
			expect.objectContaining({ lock_token: 'other-lock' }),
			false
		);
		session.close();
	});

	test('reconnects with exponential backoff that resets after a successful connection', () => {
		vi.useFakeTimers();
		const session: LockSession = openLockSession({
			resourceType: 'analysis',
			resourceId: 'analysis-1',
			onStatus: vi.fn(),
			onError: vi.fn()
		});
		expect(sockets.length).toBe(1);

		sockets[0].emit('close');
		vi.advanceTimersByTime(1_000);
		expect(sockets.length).toBe(2);

		sockets[1].emit('close');
		vi.advanceTimersByTime(999);
		expect(sockets.length).toBe(2);
		vi.advanceTimersByTime(1_001);
		expect(sockets.length).toBe(3);

		sockets[2].emit('open');
		sockets[2].emit('close');
		vi.advanceTimersByTime(1_000);
		expect(sockets.length).toBe(4);

		session.close();
	});

	test('caps reconnect backoff so a reconnect always happens within the max delay', () => {
		vi.useFakeTimers();
		const session: LockSession = openLockSession({
			resourceType: 'analysis',
			resourceId: 'analysis-1',
			onStatus: vi.fn(),
			onError: vi.fn()
		});
		let current = sockets[0];
		for (let i = 0; i < 12; i++) {
			current.emit('close');
			const before = sockets.length;
			vi.advanceTimersByTime(30_000);
			expect(sockets.length).toBe(before + 1);
			current = sockets[sockets.length - 1];
		}
		session.close();
	});
});
