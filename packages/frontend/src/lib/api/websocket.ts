import { getClientIdentity, getEditorClientId } from '#lib/stores/clientIdentity.svelte.js';
import { requireNamespace } from '#lib/stores/namespace.svelte.js';
import { isRecord } from '#lib/utils/json.js';
import { buildBackendUrl } from './client';

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
	const url = new URL(buildBackendUrl(endpoint), window.location.origin);
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
	const editorClientId = getEditorClientId();
	if (editorClientId) {
		url.searchParams.set('editor_client_id', editorClientId);
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

export interface StreamErrorMessage {
	type: 'error';
	error: string;
}

export function isErrorMessage(value: unknown): value is StreamErrorMessage {
	return isRecord(value) && value.type === 'error' && typeof value.error === 'string';
}

export function createStream<
	TSnapshot,
	TEvent = never,
	TMessage extends object = { type: string },
	TSnapshotMessage extends TMessage = TMessage
>(
	endpoint: string,
	options: {
		parse: (data: string) => TMessage | null;
		isSnapshot: (msg: TMessage) => msg is TSnapshotMessage;
		extractSnapshot: (msg: TSnapshotMessage) => TSnapshot;
		extractEvent?: (msg: Exclude<TMessage, TSnapshotMessage | StreamErrorMessage>) => TEvent;
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
			// Snapshot and error messages returned above; TypeScript cannot narrow the generic.
			const eventMessage = msg as Exclude<TMessage, TSnapshotMessage | StreamErrorMessage>;
			options.callbacks.onEvent(options.extractEvent(eventMessage));
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
