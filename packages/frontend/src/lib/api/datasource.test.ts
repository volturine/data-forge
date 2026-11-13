import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('#lib/utils/audit-log.js', () => ({
	track: vi.fn()
}));

vi.mock('#lib/stores/clientIdentity.svelte.js', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' }),
	getEditorClientId: () => 'editor-client-1'
}));

vi.mock('#lib/stores/namespace.svelte.js', () => ({
	requireNamespace: () => 'ns-a',
	isNamespaceReady: () => true
}));

const { uploadFile } = await import('./datasource');

describe('uploadFile', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test('surfaces the server message when compute is unavailable', async () => {
		const message = 'Compute is unavailable right now; try again shortly.';
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ detail: message }), {
					status: 503,
					statusText: 'Service Unavailable',
					headers: { 'Content-Type': 'application/json', 'Retry-After': '5' }
				})
			)
		);

		const result = await uploadFile(new File(['a,b\n1,2\n'], 'data.csv'), 'data');

		const error = result.match(() => null, (apiError) => apiError);
		expect(error).toMatchObject({ type: 'http', status: 503, message });
	});
});
