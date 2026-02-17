import { describe, it, expect, vi, afterEach } from 'vitest';
import { apiRequest } from '../src/lib/api/client';

afterEach(() => {
	vi.restoreAllMocks();
});

describe('apiRequest', () => {
	it('returns data on success', async () => {
		const response = new Response(JSON.stringify({ ok: true }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' }
		});
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

		const result = await apiRequest<{ ok: boolean }>('/test').match(
			(data) => data,
			() => ({ ok: false })
		);

		expect(result.ok).toBe(true);
	});

	it('returns http error on non-200 response', async () => {
		const response = new Response('Bad Request', { status: 400, statusText: 'Bad Request' });
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

		const error = await apiRequest<{ ok: boolean }>('/test').match(
			() => null,
			(err) => err
		);

		expect(error?.type).toBe('http');
		expect(error?.status).toBe(400);
	});

	it('returns parse error for invalid json', async () => {
		const response = new Response('not-json', {
			status: 200,
			headers: { 'Content-Type': 'application/json' }
		});
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

		const error = await apiRequest<{ ok: boolean }>('/test').match(
			() => null,
			(err) => err
		);

		expect(error?.type).toBe('parse');
	});
});
