import { beforeEach, describe, expect, test, vi } from 'vitest';

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
