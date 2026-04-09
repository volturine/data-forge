import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';
import { getNamespace } from '$lib/stores/namespace.svelte';
import { errAsync, okAsync, ResultAsync } from 'neverthrow';
import { BASE_URL, type ApiError } from './client';

type WebsocketMessage<T> =
	| {
			type: 'started';
	  }
	| {
			type: 'result';
			data: T;
	  }
	| {
			type: 'error';
			error: string;
			status_code?: number;
	  };

const DEV_CONNECT_TIMEOUT_MS = 500;

function resolveWebsocketOrigin(): string {
	return window.location.origin;
}

export function buildWebsocketUrl(endpoint: string): string {
	const url = new URL(`${BASE_URL}${endpoint}`, resolveWebsocketOrigin());
	url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const identity = getClientIdentity();
	const namespace = getNamespace();
	if (namespace) {
		url.searchParams.set('namespace', namespace);
	}
	if (identity.clientId) {
		url.searchParams.set('client_id', identity.clientId);
	}
	if (identity.clientSignature) {
		url.searchParams.set('client_signature', identity.clientSignature);
	}
	return url.toString();
}

export function preferHttp(): boolean {
	if (typeof window === 'undefined') return false;
	try {
		return localStorage.getItem('debug:prefer-http') === 'true';
	} catch {
		return false;
	}
}

type WsResult<T> =
	| { ok: true; data: T }
	| { ok: false; error: ApiError }
	| { ok: false; fallback: true };

function attemptWebsocket<T, Payload>(
	endpoint: string,
	action: string,
	payload: Payload
): Promise<WsResult<T>> {
	return new Promise<WsResult<T>>((resolve) => {
		const socket = new WebSocket(buildWebsocketUrl(endpoint));
		let settled = false;
		let opened = false;
		let connectTimer: number | null = null;

		const settle = (result: WsResult<T>) => {
			if (settled) return;
			settled = true;
			if (connectTimer !== null) {
				window.clearTimeout(connectTimer);
				connectTimer = null;
			}
			resolve(result);
		};

		connectTimer = window.setTimeout(() => {
			if (opened || settled) return;
			settle({ ok: false, fallback: true });
			socket.close();
		}, DEV_CONNECT_TIMEOUT_MS);

		socket.addEventListener('open', () => {
			opened = true;
			socket.send(JSON.stringify({ action, payload }));
		});

		socket.addEventListener('message', (event) => {
			let message: WebsocketMessage<T>;
			try {
				message = JSON.parse(event.data) as WebsocketMessage<T>;
			} catch {
				const preview =
					typeof event.data === 'string' ? event.data.slice(0, 100) : '[non-text payload]';
				settle({
					ok: false,
					error: { type: 'parse', message: `Failed to parse websocket response: ${preview}` }
				});
				socket.close();
				return;
			}

			if (message.type === 'started') {
				return;
			}

			if (message.type === 'error') {
				settle({
					ok: false,
					error: {
						type: 'http',
						message: message.error,
						status: message.status_code,
						statusText: 'WebSocket request failed'
					}
				});
				socket.close();
				return;
			}

			settle({ ok: true, data: message.data });
			socket.close();
		});

		socket.addEventListener('error', () => {
			if (!opened) {
				settle({ ok: false, fallback: true });
				return;
			}
			settle({ ok: false, error: { type: 'network', message: 'WebSocket request failed' } });
		});

		socket.addEventListener('close', (event) => {
			if (settled) return;
			if (!opened) {
				settle({ ok: false, fallback: true });
				return;
			}
			settle({
				ok: false,
				error: {
					type: 'network',
					message:
						event.reason || `WebSocket closed before a result was received (code ${event.code})`
				}
			});
		});
	});
}

export function websocketRequest<T, Payload>(
	endpoint: string,
	action: string,
	payload: Payload,
	fallback: () => ResultAsync<T, ApiError>
): ResultAsync<T, ApiError> {
	if (typeof window === 'undefined' || typeof WebSocket === 'undefined' || preferHttp()) {
		return fallback();
	}
	return ResultAsync.fromPromise(
		attemptWebsocket<T, Payload>(endpoint, action, payload),
		(): ApiError => ({ type: 'network', message: 'Unexpected error in WebSocket transport' })
	).andThen((result) => {
		if (result.ok) return okAsync<T, ApiError>(result.data);
		if ('fallback' in result) return fallback();
		return errAsync<T, ApiError>(result.error);
	});
}
