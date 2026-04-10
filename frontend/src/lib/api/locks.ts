import { buildWebsocketUrl, preferHttp } from './websocket';

export interface LockStatus {
	resource_type: string;
	resource_id: string;
	owner_id: string;
	lock_token: string;
	acquired_at: string;
	expires_at: string;
	last_heartbeat: string;
	is_expired: boolean;
}

interface LockWsStatus {
	type: 'status';
	resource_type: string;
	resource_id: string;
	lock: LockStatus | null;
}

interface LockWsError {
	type: 'error';
	error: string;
	status_code: number;
}

interface LockWsConnected {
	type: 'connected';
}

type LockWsMessage = LockWsConnected | LockWsStatus | LockWsError;

export interface LockSessionError {
	error: string;
	statusCode: number;
}

export interface LockSession {
	acquire(ttlSeconds?: number): void;
	release(): void;
	close(): void;
}

interface LockSessionOptions {
	resourceType: string;
	resourceId: string;
	pingMs?: number;
	onStatus: (lock: LockStatus | null, ownsLock: boolean) => void;
	onError?: (error: LockSessionError) => void;
}

const DEFAULT_PING_MS = 10_000;

export function openLockSession(options: LockSessionOptions): LockSession {
	if (preferHttp()) {
		queueMicrotask(() => {
			options.onError?.({
				error: 'Lock websocket is unavailable in the current environment',
				statusCode: 0
			});
		});
		return {
			acquire() {},
			release() {},
			close() {}
		};
	}

	const pingMs = options.pingMs ?? DEFAULT_PING_MS;
	let socket: WebSocket | null = null;
	let timer: number | null = null;
	let closed = false;
	let opened = false;
	let awaitingAcquire = false;
	let ownedToken: string | null = null;

	function clearTimer(): void {
		if (timer !== null) {
			window.clearInterval(timer);
			timer = null;
		}
	}

	function send(message: Record<string, unknown>): void {
		if (!socket || socket.readyState !== WebSocket.OPEN) return;
		socket.send(JSON.stringify(message));
	}

	function cleanup(): void {
		clearTimer();
		if (socket !== null) {
			socket.close();
			socket = null;
		}
	}

	function startPing(): void {
		clearTimer();
		timer = window.setInterval(() => {
			const ping: Record<string, unknown> = { action: 'ping' };
			if (ownedToken) ping.lock_token = ownedToken;
			send(ping);
		}, pingMs);
	}

	function handleStatus(lock: LockStatus | null): void {
		if (lock === null) {
			ownedToken = null;
			options.onStatus(null, false);
			return;
		}

		if (awaitingAcquire) {
			awaitingAcquire = false;
			ownedToken = lock.lock_token;
			options.onStatus(lock, true);
			return;
		}

		if (ownedToken !== null && lock.lock_token === ownedToken) {
			options.onStatus(lock, true);
			return;
		}

		ownedToken = null;
		options.onStatus(lock, false);
	}

	socket = new WebSocket(buildWebsocketUrl('/v1/locks/ws'));

	socket.addEventListener('open', () => {
		if (closed || !socket) return;
		opened = true;
		send({
			action: 'watch',
			resource_type: options.resourceType,
			resource_id: options.resourceId
		});
		startPing();
	});

	socket.addEventListener('message', (event) => {
		let msg: LockWsMessage;
		try {
			msg = JSON.parse(event.data) as LockWsMessage;
		} catch {
			return;
		}
		if (msg.type === 'connected') return;
		if (msg.type === 'status') {
			handleStatus(msg.lock);
			return;
		}
		awaitingAcquire = false;
		options.onError?.({ error: msg.error, statusCode: msg.status_code });
	});

	socket.addEventListener('close', () => {
		opened = false;
		clearTimer();
		socket = null;
	});

	socket.addEventListener('error', () => {
		opened = false;
		clearTimer();
		socket = null;
	});

	return {
		acquire(ttlSeconds?: number) {
			if (!opened) return;
			if (awaitingAcquire) return;
			awaitingAcquire = true;
			const message: Record<string, unknown> = { action: 'acquire' };
			if (ttlSeconds) message.ttl_seconds = ttlSeconds;
			send(message);
		},
		release() {
			if (!opened) return;
			awaitingAcquire = false;
			const message: Record<string, unknown> = { action: 'release' };
			if (ownedToken) {
				message.lock_token = ownedToken;
				ownedToken = null;
			}
			send(message);
		},
		close() {
			closed = true;
			cleanup();
		}
	};
}
