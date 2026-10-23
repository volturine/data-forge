export type MockWebSocketEvent = { data?: string; code?: number; reason?: string };

type Listener = (event?: MockWebSocketEvent) => void;

/**
 * Test double for the global `WebSocket`. `close()` records its arguments,
 * moves to CLOSED and dispatches a `close` event like the real socket does.
 */
export class MockWebSocket {
	static readonly CONNECTING = 0;
	static readonly OPEN = 1;
	static readonly CLOSED = 3;
	static instances: MockWebSocket[] = [];

	url: string;
	readyState: number = MockWebSocket.OPEN;
	sent: string[] = [];
	closeCalls: Array<{ code?: number; reason?: string }> = [];
	private listeners = new Map<string, Listener[]>();

	constructor(url = '') {
		this.url = url;
		MockWebSocket.instances.push(this);
	}

	addEventListener(type: string, listener: Listener) {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	send(message: string) {
		this.sent.push(message);
	}

	close(code?: number, reason?: string) {
		this.closeCalls.push({ code, reason });
		this.readyState = MockWebSocket.CLOSED;
		this.emit('close', { code: code ?? 1000, reason: reason ?? '' });
	}

	emit(type: string, event?: MockWebSocketEvent) {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event);
		}
	}
}
