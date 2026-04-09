import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { okAsync } from 'neverthrow';
import { websocketRequest } from './websocket';

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	getNamespace: () => 'default'
}));

type Listener = (event?: { data?: string; code?: number; reason?: string }) => void;

class MockWebSocket {
	static instances: MockWebSocket[] = [];

	url: string;
	sentMessages: string[] = [];
	private listeners = new Map<string, Listener[]>();

	constructor(url: string) {
		this.url = url;
		MockWebSocket.instances.push(this);
	}

	addEventListener(type: string, listener: Listener) {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	send(message: string) {
		this.sentMessages.push(message);
	}

	close() {
		this.emit('close', { code: 1000, reason: '' });
	}

	emit(type: string, event?: { data?: string; code?: number; reason?: string }) {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(event);
		}
	}
}

describe('websocketRequest', () => {
	beforeEach(() => {
		MockWebSocket.instances = [];
		vi.stubGlobal('WebSocket', MockWebSocket);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	test('sends compute requests over websocket with namespace context', async () => {
		const resultPromise = websocketRequest(
			'/v1/compute/ws',
			'preview',
			{ target_step_id: 'step-1' },
			() => okAsync({ fallback: true })
		);
		const socket = MockWebSocket.instances[0];
		const url = new URL(socket.url);

		expect(url.protocol).toBe('ws:');
		expect(url.pathname).toBe('/api/v1/compute/ws');
		expect(url.searchParams.get('namespace')).toBe('default');
		expect(url.searchParams.get('client_id')).toBe('client-1');
		expect(url.searchParams.get('client_signature')).toBe('signature-1');

		socket.emit('open');
		expect(socket.sentMessages).toEqual([
			JSON.stringify({ action: 'preview', payload: { target_step_id: 'step-1' } })
		]);

		socket.emit('message', {
			data: JSON.stringify({ type: 'result', data: { step_id: 'step-1', total_rows: 1 } })
		});

		const result = await resultPromise;
		expect(result.isOk()).toBe(true);
		expect(result._unsafeUnwrap()).toEqual({ step_id: 'step-1', total_rows: 1 });
	});
});
