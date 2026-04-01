import type { ResultAsync } from 'neverthrow';
import { apiRequest, type ApiError } from './client';
import { buildWebsocketUrl } from './websocket';

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

export interface LockRelease {
	released: boolean;
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

export interface LockWatcher {
	close(): void;
}

interface LockWatcherOptions {
	resourceType: string;
	resourceId: string;
	token: string | null;
	pingMs?: number;
	onStatus: (lock: LockStatus | null) => void;
	onError?: (error: string) => void;
}

const DEFAULT_PING_MS = 10_000;

export function watchLock(options: LockWatcherOptions): LockWatcher {
	const pingMs = options.pingMs ?? DEFAULT_PING_MS;
	let socket: WebSocket | null = null;
	let timer: number | null = null;
	let closed = false;

	function cleanup() {
		closed = true;
		if (timer !== null) {
			window.clearInterval(timer);
			timer = null;
		}
		if (socket !== null) {
			socket.close();
			socket = null;
		}
	}

	function connect() {
		if (closed) return;
		socket = new WebSocket(buildWebsocketUrl('/v1/locks/ws'));

		socket.addEventListener('open', () => {
			if (closed || !socket) return;
			const watch: Record<string, unknown> = {
				action: 'watch',
				resource_type: options.resourceType,
				resource_id: options.resourceId
			};
			if (options.token) watch.lock_token = options.token;
			socket.send(JSON.stringify(watch));

			timer = window.setInterval(() => {
				if (!socket || socket.readyState !== WebSocket.OPEN) return;
				const ping: Record<string, unknown> = { action: 'ping' };
				if (options.token) ping.lock_token = options.token;
				socket.send(JSON.stringify(ping));
			}, pingMs);
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
				options.onStatus(msg.lock);
				return;
			}
			if (msg.type === 'error') {
				options.onError?.(msg.error);
			}
		});

		socket.addEventListener('close', () => {
			socket = null;
		});

		socket.addEventListener('error', () => {
			socket = null;
		});
	}

	connect();

	return { close: cleanup };
}

export function acquireLock(
	resourceType: string,
	resourceId: string,
	ttl?: number
): ResultAsync<LockStatus, ApiError> {
	return apiRequest<LockStatus>('/v1/locks', {
		method: 'POST',
		body: JSON.stringify({
			resource_type: resourceType,
			resource_id: resourceId,
			...(ttl ? { ttl_seconds: ttl } : {})
		})
	});
}

export function getLockStatus(
	resourceType: string,
	resourceId: string
): ResultAsync<LockStatus | null, ApiError> {
	return apiRequest<LockStatus | null>(`/v1/locks/${resourceType}/${resourceId}`);
}

export function heartbeatLock(
	resourceType: string,
	resourceId: string,
	token: string,
	ttl?: number
): ResultAsync<LockStatus, ApiError> {
	return apiRequest<LockStatus>(`/v1/locks/${resourceType}/${resourceId}/heartbeat`, {
		method: 'POST',
		body: JSON.stringify({
			lock_token: token,
			...(ttl ? { ttl_seconds: ttl } : {})
		})
	});
}

export function releaseLock(
	resourceType: string,
	resourceId: string,
	token: string
): ResultAsync<LockRelease, ApiError> {
	return apiRequest<LockRelease>(`/v1/locks/${resourceType}/${resourceId}`, {
		method: 'DELETE',
		body: JSON.stringify({ lock_token: token })
	});
}
