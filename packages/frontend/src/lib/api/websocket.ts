import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';
import { requireNamespace } from '$lib/stores/namespace.svelte';

const CLOSE_NORMAL = 1000;
const CLOSE_GOING_AWAY = 1001;
const CLOSE_NO_STATUS = 1005;
const CLOSE_UNLOAD = 1000;
const UNLOAD_REASON = 'Page unloading';

const sockets = new Set<WebSocket>();
const sources = new Set<EventSource>();
let bound = false;

function closeSocket(socket: WebSocket, code: number, reason?: string): void {
	if (socket.readyState !== WebSocket.OPEN && socket.readyState !== WebSocket.CONNECTING) return;
	sockets.delete(socket);
	socket.close(code, reason);
}

function closeOwnedSockets(): void {
	for (const socket of [...sockets]) {
		closeSocket(socket, CLOSE_UNLOAD, UNLOAD_REASON);
	}
}

function closeSource(source: EventSource): void {
	if (source.readyState === EventSource.CLOSED) {
		sources.delete(source);
		return;
	}
	sources.delete(source);
	source.close();
}

function closeOwnedSources(): void {
	for (const source of [...sources]) {
		closeSource(source);
	}
}

function closeOwnedConnections(): void {
	closeOwnedSockets();
	closeOwnedSources();
}

function bindUnloadCleanup(): void {
	if (bound) return;
	if (typeof window === 'undefined') return;
	bound = true;
	window.addEventListener('pagehide', closeOwnedConnections);
	window.addEventListener('beforeunload', closeOwnedConnections);
}

export function createOwnedWebSocket(endpoint: string): WebSocket {
	const socket = new WebSocket(buildWebsocketUrl(endpoint));
	bindUnloadCleanup();
	sockets.add(socket);
	socket.addEventListener('close', () => {
		sockets.delete(socket);
	});
	return socket;
}

export function closeOwnedWebSocket(socket: WebSocket, code = CLOSE_NORMAL, reason?: string): void {
	closeSocket(socket, code, reason);
}

export function createOwnedEventSource(url: string): EventSource {
	const source = new EventSource(url);
	const close = source.close.bind(source);
	bindUnloadCleanup();
	sources.add(source);
	source.close = () => {
		sources.delete(source);
		close();
	};
	source.addEventListener('error', () => {
		if (source.readyState !== EventSource.CLOSED) return;
		sources.delete(source);
	});
	return source;
}

export function closeOwnedEventSource(source: EventSource): void {
	closeSource(source);
}

export function buildWebsocketUrl(endpoint: string): string {
	const base = import.meta.env.DEV
		? `http://${window.location.hostname}:${import.meta.env.VITE_BACKEND_PORT ?? '8000'}`
		: window.location.origin;
	const url = new URL(`/api${endpoint}`, base);
	url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
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
	const socket = createOwnedWebSocket(endpoint);

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
		if (
			event.code !== CLOSE_NORMAL &&
			event.code !== CLOSE_GOING_AWAY &&
			event.code !== CLOSE_NO_STATUS
		) {
			options.callbacks.onError(event.reason || `Connection closed (code ${event.code})`);
		}
		options.callbacks.onClose();
	});

	return {
		close() {
			closeOwnedWebSocket(socket);
		}
	};
}
