/**
 * Create a mock API client for testing
 */
export function createMockApiClient() {
	return {
		get: vi.fn(),
		post: vi.fn(),
		put: vi.fn(),
		delete: vi.fn(),
		patch: vi.fn()
	};
}

/**
 * Mock fetch responses
 */
export function mockFetch(data: unknown, status = 200) {
	global.fetch = vi.fn().mockResolvedValue({
		ok: status >= 200 && status < 300,
		status,
		json: async () => data,
		text: async () => JSON.stringify(data),
		headers: new Headers({
			'content-type': 'application/json'
		})
	});
}

/**
 * Mock fetch error
 */
export function mockFetchError(message = 'Network error', _status = 500) {
	global.fetch = vi.fn().mockRejectedValue(new Error(message));
}

/**
 * Wait for a condition to be true
 */
export async function waitFor(
	condition: () => boolean,
	timeout = 1000,
	interval = 50
): Promise<void> {
	const startTime = Date.now();
	while (!condition()) {
		if (Date.now() - startTime > timeout) {
			throw new Error('Timeout waiting for condition');
		}
		await new Promise((resolve) => setTimeout(resolve, interval));
	}
}

/**
 * Create mock datasource
 */
export function createMockDataSource(overrides: Record<string, unknown> = {}) {
	return {
		id: 'ds-123',
		name: 'Test DataSource',
		source_type: 'file',
		config: {
			file_path: '/test/data.csv',
			file_type: 'csv',
			options: {}
		},
		schema_cache: null,
		created_at: new Date().toISOString(),
		...overrides
	};
}

/**
 * Create mock analysis
 */
export function createMockAnalysis(overrides: Record<string, unknown> = {}) {
	return {
		id: 'analysis-123',
		name: 'Test Analysis',
		description: 'Test description',
		pipeline_definition: {
			steps: [],
			datasource_ids: [],
			tabs: []
		},
		status: 'draft',
		result_path: null,
		thumbnail: null,
		created_at: new Date().toISOString(),
		updated_at: new Date().toISOString(),
		...overrides
	};
}

/**
 * Create mock compute job
 */
export function createMockJob(overrides = {}) {
	return {
		job_id: 'job-123',
		status: 'pending',
		progress: 0,
		result: null,
		error: null,
		started_at: new Date().toISOString(),
		completed_at: null,
		...overrides
	};
}

declare global {
	const vi: (typeof import('vitest'))['vi'];
}
