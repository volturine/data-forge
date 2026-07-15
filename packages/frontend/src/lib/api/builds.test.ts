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

const builds = await import('./builds');

function makeResult(tag: string) {
	return {
		tag,
		match: vi.fn()
	};
}

describe('builds api', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test('coalesces identical in-flight list requests', () => {
		const result = makeResult('builds');
		mockApiRequest.mockReturnValue(result);

		const first = builds.listBuilds({ datasource_id: 'ds-1', limit: 50 });
		const second = builds.listBuilds({ datasource_id: 'ds-1', limit: 50 });

		expect(first).toBe(result);
		expect(second).toBe(result);
		expect(mockApiRequest).toHaveBeenCalledTimes(1);
		expect(mockApiRequest).toHaveBeenCalledWith('/v1/compute/builds?datasource_id=ds-1&limit=50');
	});
});
