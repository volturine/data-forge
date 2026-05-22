import { describe, expect, test, vi, beforeEach } from 'vitest';

const mockApiRequest = vi.fn();

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true
}));

vi.mock('./client', () => ({
	apiRequest: (...args: unknown[]) => mockApiRequest(...args)
}));

const engineRuns = await import('./engine-runs');

function makeResult(tag: string) {
	return {
		tag,
		match: vi.fn()
	};
}

describe('engine-runs api', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test('coalesces identical in-flight list requests', () => {
		const result = makeResult('runs');
		mockApiRequest.mockReturnValue(result);

		const first = engineRuns.listEngineRuns({ datasource_id: 'ds-1', limit: 50 });
		const second = engineRuns.listEngineRuns({ datasource_id: 'ds-1', limit: 50 });

		expect(first).toBe(result);
		expect(second).toBe(result);
		expect(mockApiRequest).toHaveBeenCalledTimes(1);
		expect(mockApiRequest).toHaveBeenCalledWith('/v1/engine-runs?datasource_id=ds-1&limit=50');
	});
});
