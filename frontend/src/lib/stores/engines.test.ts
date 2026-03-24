import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest';
import type { EngineStatusResponse, EngineListResponse } from '$lib/types/compute';

const mockListEngines = vi.fn();
const mockShutdownEngine = vi.fn();
const mockConfigFetch = vi.fn();

let mockConfig: { engine_pooling_interval: number } | null = null;

vi.mock('$lib/api/compute', () => ({
	listEngines: (...args: unknown[]) => mockListEngines(...args),
	shutdownEngine: (...args: unknown[]) => mockShutdownEngine(...args)
}));

vi.mock('./config.svelte', () => ({
	configStore: {
		get config() {
			return mockConfig;
		},
		fetch: (...args: unknown[]) => mockConfigFetch(...args),
		get enginePoolingInterval() {
			return mockConfig?.engine_pooling_interval ?? 5000;
		}
	}
}));

const { EnginesStore } = await import('./engines.svelte');

function makeEngine(overrides: Partial<EngineStatusResponse> = {}): EngineStatusResponse {
	return {
		analysis_id: `analysis-${crypto.randomUUID().slice(0, 8)}`,
		status: 'healthy',
		process_id: 1234,
		last_activity: new Date().toISOString(),
		current_job_id: null,
		resource_config: null,
		effective_resources: null,
		defaults: null,
		...overrides
	};
}

function mockListSuccess(engines: EngineStatusResponse[]) {
	const response: EngineListResponse = { engines };
	mockListEngines.mockReturnValue({
		match: (onOk: (r: EngineListResponse) => void) => {
			onOk(response);
			return Promise.resolve();
		}
	});
}

function mockListError(message: string) {
	mockListEngines.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

function mockShutdownSuccess() {
	mockShutdownEngine.mockReturnValue({
		match: (onOk: () => void) => {
			onOk();
			return Promise.resolve();
		}
	});
}

function mockShutdownError(message: string) {
	mockShutdownEngine.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

describe('EnginesStore', () => {
	let store: InstanceType<typeof EnginesStore>;

	beforeEach(() => {
		vi.useFakeTimers();
		vi.clearAllMocks();
		mockConfig = null;
		mockConfigFetch.mockResolvedValue(undefined);
		store = new EnginesStore();
	});

	afterEach(() => {
		store.stopPolling();
		vi.useRealTimers();
	});

	describe('initial state', () => {
		test('engines is empty array', () => {
			expect(store.engines).toEqual([]);
		});

		test('loading is false', () => {
			expect(store.loading).toBe(false);
		});

		test('error is null', () => {
			expect(store.error).toBeNull();
		});

		test('count is 0', () => {
			expect(store.count).toBe(0);
		});

		test('isPolling is false', () => {
			expect(store.isPolling).toBe(false);
		});
	});

	describe('fetch success', () => {
		test('populates engines and clears loading', async () => {
			const eng = [makeEngine({ analysis_id: 'a-1' }), makeEngine({ analysis_id: 'a-2' })];
			mockListSuccess(eng);

			await store.fetch();

			expect(store.engines).toHaveLength(2);
			expect(store.engines[0].analysis_id).toBe('a-1');
			expect(store.loading).toBe(false);
			expect(store.error).toBeNull();
		});

		test('count reflects engine list length', async () => {
			mockListSuccess([makeEngine(), makeEngine(), makeEngine()]);
			await store.fetch();
			expect(store.count).toBe(3);
		});
	});

	describe('fetch error', () => {
		test('sets error and clears loading', async () => {
			mockListError('Connection refused');

			await store.fetch();

			expect(store.error).toBe('Connection refused');
			expect(store.loading).toBe(false);
			expect(store.engines).toEqual([]);
		});
	});

	describe('shutdownEngine success', () => {
		test('removes engine from list', async () => {
			mockListSuccess([makeEngine({ analysis_id: 'a-1' }), makeEngine({ analysis_id: 'a-2' })]);
			await store.fetch();
			expect(store.engines).toHaveLength(2);

			mockShutdownSuccess();
			await store.shutdownEngine('a-1');

			expect(store.engines).toHaveLength(1);
			expect(store.engines[0].analysis_id).toBe('a-2');
		});
	});

	describe('shutdownEngine error', () => {
		test('sets error and throws', async () => {
			mockListSuccess([makeEngine({ analysis_id: 'a-1' })]);
			await store.fetch();

			mockShutdownError('Permission denied');

			await expect(store.shutdownEngine('a-1')).rejects.toThrow('Permission denied');
			expect(store.error).toBe('Permission denied');
			expect(store.engines).toHaveLength(1);
		});
	});

	describe('startPolling', () => {
		test('sets isPolling to true', async () => {
			mockListSuccess([]);
			await store.startPolling();
			expect(store.isPolling).toBe(true);
		});

		test('fetches config if not loaded', async () => {
			mockListSuccess([]);
			mockConfig = null;

			await store.startPolling();

			expect(mockConfigFetch).toHaveBeenCalledTimes(1);
		});

		test('skips config fetch if already loaded', async () => {
			mockListSuccess([]);
			mockConfig = { engine_pooling_interval: 3000 };

			await store.startPolling();

			expect(mockConfigFetch).not.toHaveBeenCalled();
		});

		test('calls fetch immediately', async () => {
			mockListSuccess([]);
			await store.startPolling();
			expect(mockListEngines).toHaveBeenCalledTimes(1);
		});

		test('second startPolling is a no-op', async () => {
			mockListSuccess([]);
			await store.startPolling();
			await store.startPolling();
			expect(mockListEngines).toHaveBeenCalledTimes(1);
		});

		test('uses config interval for polling', async () => {
			mockConfig = { engine_pooling_interval: 2000 };
			mockListSuccess([]);

			await store.startPolling();
			expect(mockListEngines).toHaveBeenCalledTimes(1);

			vi.advanceTimersByTime(2000);
			expect(mockListEngines).toHaveBeenCalledTimes(2);

			vi.advanceTimersByTime(2000);
			expect(mockListEngines).toHaveBeenCalledTimes(3);
		});

		test('uses default interval when config not available', async () => {
			mockConfig = null;
			mockListSuccess([]);

			await store.startPolling();
			expect(mockListEngines).toHaveBeenCalledTimes(1);

			vi.advanceTimersByTime(5000);
			expect(mockListEngines).toHaveBeenCalledTimes(2);
		});
	});

	describe('stopPolling', () => {
		test('sets isPolling to false', async () => {
			mockListSuccess([]);
			await store.startPolling();
			expect(store.isPolling).toBe(true);

			store.stopPolling();
			expect(store.isPolling).toBe(false);
		});

		test('stops interval ticks', async () => {
			mockConfig = { engine_pooling_interval: 1000 };
			mockListSuccess([]);

			await store.startPolling();
			expect(mockListEngines).toHaveBeenCalledTimes(1);

			store.stopPolling();
			vi.advanceTimersByTime(5000);
			expect(mockListEngines).toHaveBeenCalledTimes(1);
		});

		test('noop when not polling', () => {
			expect(() => store.stopPolling()).not.toThrow();
			expect(store.isPolling).toBe(false);
		});

		test('can restart polling after stop', async () => {
			mockConfig = { engine_pooling_interval: 1000 };
			mockListSuccess([]);

			await store.startPolling();
			store.stopPolling();

			await store.startPolling();
			expect(store.isPolling).toBe(true);
			expect(mockListEngines).toHaveBeenCalledTimes(2);
		});
	});

	describe('stale interval behavior', () => {
		test('interval is captured once at start — config change after start does not affect tick rate', async () => {
			mockConfig = { engine_pooling_interval: 1000 };
			mockListSuccess([]);

			await store.startPolling();
			expect(mockListEngines).toHaveBeenCalledTimes(1);

			mockConfig = { engine_pooling_interval: 9999 };

			vi.advanceTimersByTime(1000);
			expect(mockListEngines).toHaveBeenCalledTimes(2);

			vi.advanceTimersByTime(1000);
			expect(mockListEngines).toHaveBeenCalledTimes(3);
		});
	});
});
