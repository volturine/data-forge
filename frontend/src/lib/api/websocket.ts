import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';
import { getNamespace } from '$lib/stores/namespace.svelte';
import { ResultAsync } from 'neverthrow';
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

function createApiError(error: unknown): ApiError {
	if (typeof error === 'object' && error !== null && 'type' in error && 'message' in error) {
		return error as ApiError;
	}
	return {
		type: 'network',
		message: error instanceof Error ? error.message : 'WebSocket request failed'
	};
}

function buildWebsocketUrl(endpoint: string): string {
	const url = new URL(`${BASE_URL}${endpoint}`, window.location.origin);
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

export function websocketRequest<T, Payload>(
	endpoint: string,
	action: string,
	payload: Payload,
	fallback: () => ResultAsync<T, ApiError>
): ResultAsync<T, ApiError> {
	if (typeof window === 'undefined' || typeof WebSocket === 'undefined') {
		return fallback();
	}
	return ResultAsync.fromPromise(
		new Promise<T>((resolve, reject) => {
			const socket = new WebSocket(buildWebsocketUrl(endpoint));
			let settled = false;

			const settle = (callback: () => void) => {
				if (settled) return;
				settled = true;
				callback();
			};

			socket.addEventListener('open', () => {
				socket.send(JSON.stringify({ action, payload }));
			});

			socket.addEventListener('message', (event) => {
				let message: WebsocketMessage<T>;
				try {
					message = JSON.parse(event.data) as WebsocketMessage<T>;
				} catch {
					const preview =
						typeof event.data === 'string' ? event.data.slice(0, 100) : '[non-text payload]';
					settle(() =>
						reject({
							type: 'parse',
							message: `Failed to parse websocket response: ${preview}`
						})
					);
					socket.close();
					return;
				}

				if (message.type === 'started') {
					return;
				}

				if (message.type === 'error') {
					settle(() =>
						reject({
							type: 'http',
							message: message.error,
							status: message.status_code,
							statusText: 'WebSocket request failed'
						})
					);
					socket.close();
					return;
				}

				settle(() => resolve(message.data));
				socket.close();
			});

			socket.addEventListener('error', () => {
				settle(() => reject({ type: 'network', message: 'WebSocket request failed' }));
			});

			socket.addEventListener('close', (event) => {
				if (settled) return;
				settle(() =>
					reject({
						type: 'network',
						message:
							event.reason || `WebSocket closed before a result was received (code ${event.code})`
					})
				);
			});
		}),
		createApiError
	);
}
