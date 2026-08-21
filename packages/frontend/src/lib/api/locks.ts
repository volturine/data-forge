import { closeOwnedWebSocket, createOwnedWebSocket, preferHttp } from './websocket';

const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 30_000;

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
	let reconnectTimer: number | null = null;
	let closed = false;
	let opened = false;
	let awaitingAcquire = false;
	let wantsAcquire = false;
	let attemptedAcquireOnExistingLock = false;
	let ownedToken: string | null = null;
	let reconnectAttempt = 0;

	function clearTimer(): void {
		if (timer !== null) {
			window.clearInterval(timer);
			timer = null;
		}
	}

	function clearReconnectTimer(): void {
		if (reconnectTimer !== null) {
			window.clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
	}

	function send(message: Record<string, unknown>): void {
		if (!socket || socket.readyState !== WebSocket.OPEN) return;
		socket.send(JSON.stringify(message));
	}

	function sendAcquire(ttlSeconds?: number): void {
		if (!opened || awaitingAcquire) return;
		awaitingAcquire = true;
		const message: Record<string, unknown> = { action: 'acquire' };
		if (ttlSeconds) message.ttl_seconds = ttlSeconds;
		send(message);
	}

	function cleanup(): void {
		clearTimer();
		clearReconnectTimer();
		if (socket !== null) {
			closeOwnedWebSocket(socket);
			socket = null;
		}
	}

	function resetOwnership(): void {
		opened = false;
		awaitingAcquire = false;
		attemptedAcquireOnExistingLock = false;
		ownedToken = null;
		options.onStatus(null, false);
	}

	function scheduleReconnect(): void {
		if (closed || reconnectTimer !== null) return;
		const backoff = Math.min(
			RECONNECT_BASE_DELAY_MS * 2 ** reconnectAttempt,
			RECONNECT_MAX_DELAY_MS
		);
		const delay = backoff / 2 + Math.random() * (backoff / 2);
		reconnectAttempt += 1;
		reconnectTimer = window.setTimeout(() => {
			reconnectTimer = null;
			if (closed) return;
			connect();
		}, delay);
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
			awaitingAcquire = false;
			attemptedAcquireOnExistingLock = false;
			ownedToken = null;
			options.onStatus(null, false);
			if (wantsAcquire) sendAcquire();
			return;
		}

		if (awaitingAcquire) {
			awaitingAcquire = false;
			attemptedAcquireOnExistingLock = false;
			ownedToken = lock.lock_token;
			options.onStatus(lock, true);
			return;
		}

		if (ownedToken !== null && lock.lock_token === ownedToken) {
			attemptedAcquireOnExistingLock = false;
			options.onStatus(lock, true);
			return;
		}

		if (wantsAcquire && !attemptedAcquireOnExistingLock) {
			attemptedAcquireOnExistingLock = true;
			sendAcquire();
			return;
		}

		ownedToken = null;
		options.onStatus(lock, false);
	}

	function connect(): void {
		clearReconnectTimer();
		socket = createOwnedWebSocket('/v1/locks/ws');

		socket.addEventListener('open', () => {
			if (closed || !socket) return;
			opened = true;
			reconnectAttempt = 0;
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
			clearTimer();
			socket = null;
			if (closed) {
				opened = false;
				return;
			}
			resetOwnership();
			scheduleReconnect();
		});

		socket.addEventListener('error', () => {
			clearTimer();
			socket = null;
			if (closed) {
				opened = false;
				return;
			}
			resetOwnership();
			scheduleReconnect();
		});
	}

	connect();

	return {
		acquire(ttlSeconds?: number) {
			wantsAcquire = true;
			attemptedAcquireOnExistingLock = false;
			sendAcquire(ttlSeconds);
		},
		release() {
			wantsAcquire = false;
			attemptedAcquireOnExistingLock = false;
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
