import { describe, expect, test, vi, beforeEach } from 'vitest';

const mockApiRequest = vi.fn();

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' }),
	getEditorClientId: () => 'editor-client-1'
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true
}));

vi.mock('./client', () => ({
	apiRequest: (...args: unknown[]) => mockApiRequest(...args)
}));

const computeWorkerRuns = await import('./compute-worker-runs');

function makeResult(tag: string) {
	return {
		tag,
		match: vi.fn()
	};
}

describe('compute-worker-runs api', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test('coalesces identical in-flight list requests', () => {
		const result = makeResult('runs');
		mockApiRequest.mockReturnValue(result);

		const first = computeWorkerRuns.listComputeWorkerRuns({ datasource_id: 'ds-1', limit: 50 });
		const second = computeWorkerRuns.listComputeWorkerRuns({ datasource_id: 'ds-1', limit: 50 });

		expect(first).toBe(result);
		expect(second).toBe(result);
		expect(mockApiRequest).toHaveBeenCalledTimes(1);
		expect(mockApiRequest).toHaveBeenCalledWith(
			'/v1/compute-worker-runs?datasource_id=ds-1&limit=50'
		);
	});
});
