import { beforeEach, describe, expect, test, vi } from 'vitest';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { Page, Request, Response as PlaywrightResponse } from '@playwright/test';
import { createRequestTrace } from '../../../tests/utils/request-trace';

const mockTrack = vi.fn();

vi.mock('$lib/utils/audit-log', () => ({
	track: (...args: unknown[]) => mockTrack(...args)
}));

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'ns-a',
	isNamespaceReady: () => true
}));

const { apiRequest, apiConditionalRequestWithHeaders } = await import('./client');

describe('api client cache policy', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ ok: true }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				})
			)
		);
	});

	test('defaults requests to no-store so namespace-scoped reads do not reuse stale responses', async () => {
		await apiRequest<{ ok: boolean }>('/v1/test').match(
			(value) => value,
			(error) => {
				throw error;
			}
		);

		expect(fetch).toHaveBeenCalledWith(
			'/api/v1/test',
			expect.objectContaining({ cache: 'no-store' })
		);
	});

	test('preserves an explicit cache mode override', async () => {
		await apiRequest<{ ok: boolean }>('/v1/test', { cache: 'reload' }).match(
			(value) => value,
			(error) => {
				throw error;
			}
		);

		expect(fetch).toHaveBeenCalledWith(
			'/api/v1/test',
			expect.objectContaining({ cache: 'reload' })
		);
	});

	test('preserves a caller request ID and merges caller headers', async () => {
		await apiRequest<{ ok: boolean }>('/v1/test', {
			headers: { 'X-Request-ID': 'caller-request-id', 'X-Custom': 'caller-value' }
		}).match(
			(value) => value,
			(error) => {
				throw error;
			}
		);

		const requestInit = vi.mocked(fetch).mock.calls[0]?.[1];
		const headers = new Headers(requestInit?.headers);
		expect(headers.get('X-Request-ID')).toBe('caller-request-id');
		expect(headers.get('X-Custom')).toBe('caller-value');
		expect(headers.get('X-Client-Id')).toBe('client-1');
		expect(headers.get('X-Client-Signature')).toBe('signature-1');
		expect(headers.get('X-Namespace')).toBe('ns-a');
	});

	test('generates a different request ID for each fetch', async () => {
		await Promise.all([apiRequest('/v1/first'), apiRequest('/v1/second')]);

		const requestIds = vi
			.mocked(fetch)
			.mock.calls.map(([, init]) => new Headers(init?.headers).get('X-Request-ID'));
		expect(requestIds).toHaveLength(2);
		expect(requestIds[0]).toMatch(
			/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
		);
		expect(requestIds[1]).toMatch(
			/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
		);
		expect(new Set(requestIds).size).toBe(2);
	});

	test('generates request IDs when crypto.randomUUID is unavailable', async () => {
		const originalCrypto = globalThis.crypto;
		vi.stubGlobal('crypto', {
			getRandomValues(bytes: Uint8Array) {
				bytes.forEach((_, index) => {
					bytes[index] = index;
				});
				return bytes;
			}
		});

		try {
			await apiRequest('/v1/test');
			const requestInit = vi.mocked(fetch).mock.calls[0]?.[1];
			const requestId = new Headers(requestInit?.headers).get('X-Request-ID');
			expect(requestId).toMatch(
				/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
			);
		} finally {
			vi.stubGlobal('crypto', originalCrypto);
		}
	});

	test('generates a request ID before a fetch that later aborts', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')));

		const result = await apiRequest('/v1/test');
		const requestInit = vi.mocked(fetch).mock.calls[0]?.[1];
		const requestId = new Headers(requestInit?.headers).get('X-Request-ID');

		expect(result.isErr()).toBe(true);
		expect(requestId).toMatch(
			/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
		);
	});

	test('request tracing records the outgoing ID when a request aborts before response', async () => {
		const dir = mkdtempSync(path.join(tmpdir(), 'data-forge-request-trace-'));
		vi.stubEnv('PLAYWRIGHT_REQUEST_TRACE_DIR', dir);
		const handlers = new Map<string, Array<(...args: unknown[]) => void>>();
		const page = {
			on(event: string, handler: (...args: unknown[]) => void) {
				const listeners = handlers.get(event) ?? [];
				listeners.push(handler);
				handlers.set(event, listeners);
			},
			off(event: string, handler: (...args: unknown[]) => void) {
				handlers.set(
					event,
					(handlers.get(event) ?? []).filter((listener) => listener !== handler)
				);
			}
		} as unknown as Page;
		const trace = createRequestTrace(page, 0, 'bootstrap', 'bootstrap-abort');
		const request = {
			url: () => 'https://app.example/api/v1/config',
			method: () => 'GET',
			postData: () => null,
			headers: () => ({ 'x-request-id': 'client-request-id' }),
			failure: () => ({ errorText: 'net::ERR_ABORTED' })
		} as unknown as Request;
		const successfulRequest = {
			url: () => 'https://app.example/api/v1/auth/me',
			method: () => 'GET',
			postData: () => null,
			headers: () => ({ 'x-request-id': 'successful-client-request-id' })
		} as unknown as Request;
		const response = {
			request: () => successfulRequest,
			status: () => 200,
			headers: () => ({ 'x-request-id': 'server-request-id', 'server-timing': 'app;dur=42' }),
			url: () => 'https://app.example/api/v1/auth/me'
		} as unknown as PlaywrightResponse;

		try {
			handlers.get('request')?.forEach((handler) => handler(request));
			handlers.get('requestfailed')?.forEach((handler) => handler(request));
			handlers.get('request')?.forEach((handler) => handler(successfulRequest));
			handlers.get('response')?.forEach((handler) => handler(response));
			handlers.get('requestfinished')?.forEach((handler) => handler(successfulRequest));
			await trace?.attach();

			const file = path.join(dir, 'worker-0-bootstrap-abort-bootstrap.jsonl');
			const entries = readFileSync(file, 'utf8')
				.trim()
				.split('\n')
				.map((line) => JSON.parse(line)) as {
				clientRequestId: string | null;
				requestId: string | null;
				failureText: string | null;
			}[];
			expect(entries[0]?.clientRequestId).toBe('client-request-id');
			expect(entries[0]?.requestId).toBeNull();
			expect(entries[0]?.failureText).toBe('net::ERR_ABORTED');
			expect(entries[1]?.clientRequestId).toBe('successful-client-request-id');
			expect(entries[1]?.requestId).toBe('server-request-id');
		} finally {
			rmSync(dir, { recursive: true, force: true });
			vi.unstubAllEnvs();
		}
	});

	test('discards an in-flight response after the namespace epoch changes', async () => {
		let resolveFetch: ((response: Response) => void) | undefined;
		vi.stubGlobal(
			'fetch',
			vi.fn(
				() =>
					new Promise<Response>((resolve) => {
						resolveFetch = resolve;
					})
			)
		);

		const request = apiRequest<{ ok: boolean }>('/v1/test');
		window.dispatchEvent(new Event('dataforge:namespace-will-change'));
		resolveFetch?.(
			new Response(JSON.stringify({ ok: true }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		);

		const result = await request;
		expect(result.isErr()).toBe(true);
		if (result.isErr()) expect(result.error.message).toContain('namespace changed');
	});
});

describe('api conditional requests', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test('returns notModified for a 304 response instead of an error', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(new Response(null, { status: 304, headers: { ETag: '"a-1"' } }))
		);

		const result = await apiConditionalRequestWithHeaders<{ ok: boolean }>('/v1/test', {
			headers: { 'If-None-Match': '"a-1"' }
		});

		expect(result.isOk()).toBe(true);
		if (result.isOk()) {
			expect(result.value.notModified).toBe(true);
			expect(result.value.headers.get('ETag')).toBe('"a-1"');
		}
	});

	test('returns data on a normal 200 response', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ ok: true }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				})
			)
		);

		const result = await apiConditionalRequestWithHeaders<{ ok: boolean }>('/v1/test', {
			headers: { 'If-None-Match': '"a-1"' }
		});

		expect(result.isOk()).toBe(true);
		if (result.isOk()) {
			expect(result.value.notModified).toBe(false);
			if (!result.value.notModified) expect(result.value.data).toEqual({ ok: true });
		}
	});

	test('still surfaces HTTP errors as ApiError', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(new Response('{"detail":"missing"}', { status: 404 }))
		);

		const result = await apiConditionalRequestWithHeaders<{ ok: boolean }>('/v1/test', {
			headers: { 'If-None-Match': '"a-1"' }
		});

		expect(result.isErr()).toBe(true);
		if (result.isErr()) expect(result.error.status).toBe(404);
	});
});
