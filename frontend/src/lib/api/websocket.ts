import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';
import { requireNamespace } from '$lib/stores/namespace.svelte';
import { BASE_URL } from './client';

export function buildWebsocketUrl(endpoint: string): string {
	const url = new URL(`${BASE_URL}${endpoint}`, window.location.origin);
	url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const identity = getClientIdentity();
	const namespace = requireNamespace();
	url.searchParams.set('namespace', namespace);
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

export interface StreamCallbacks<TSnapshot, TEvent = never> {
	onSnapshot: (snapshot: TSnapshot) => void;
	onEvent?: (event: TEvent) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

export interface StreamHandle {
	close: () => void;
}

function isErrorMessage(msg: { type: string }): msg is { type: 'error'; error: string } {
	if (msg.type !== 'error') return false;
	const value = msg as Record<string, unknown>;
	return typeof value.error === 'string';
}

export function createStream<
	TSnapshot,
	TEvent = never,
	TMessage extends { type: string } = { type: string }
>(
	endpoint: string,
	options: {
		parse: (data: string) => TMessage | null;
		isSnapshot: (msg: TMessage) => boolean;
		extractSnapshot: (msg: TMessage) => TSnapshot;
		extractEvent?: (msg: TMessage) => TEvent;
		callbacks: StreamCallbacks<TSnapshot, TEvent>;
	}
): StreamHandle {
	const socket = new WebSocket(buildWebsocketUrl(endpoint));

	socket.addEventListener('message', (event) => {
		const msg = options.parse(event.data as string);
		if (!msg) return;
		if (options.isSnapshot(msg)) {
			options.callbacks.onSnapshot(options.extractSnapshot(msg));
			return;
		}
		if (isErrorMessage(msg)) {
			options.callbacks.onError(msg.error);
			return;
		}
		if (options.extractEvent && options.callbacks.onEvent) {
			options.callbacks.onEvent(options.extractEvent(msg));
		}
	});

	socket.addEventListener('error', () => {
		options.callbacks.onError('WebSocket connection failed');
	});

	socket.addEventListener('close', (event) => {
		if (event.code !== 1000 && event.code !== 1005) {
			options.callbacks.onError(event.reason || `Connection closed (code ${event.code})`);
		}
		options.callbacks.onClose();
	});

	return {
		close() {
			if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
				socket.close(1000);
			}
		}
	};
}
