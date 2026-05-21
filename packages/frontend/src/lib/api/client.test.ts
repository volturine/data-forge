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

const { apiRequest } = await import('./client');

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
});
