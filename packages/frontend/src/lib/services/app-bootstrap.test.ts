import { describe, test, expect, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
const mockResolve = vi.fn();
const mockInitNamespace = vi.fn();

const mockConfig = {
	config: null as { auth_required?: boolean; default_namespace?: string } | null,
	error: null as string | null,
	authRequired: true,
	settled: false,
	fetch: (...args: unknown[]) => mockFetch(...args)
};

const mockAuth = {
	status: 'unknown' as string,
	error: null as string | null,
	authenticated: false,
	bootstrapFailed: false,
	resolve: (...args: unknown[]) => mockResolve(...args)
};

let namespaceStatus: 'pending' | 'ready' | 'failed' = 'pending';
let namespaceError: string | null = null;

function createDeferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((resolvePromise) => {
		resolve = resolvePromise;
	});
	return { promise, resolve };
}

vi.mock('#lib/stores/config.svelte.js', () => ({
	configStore: mockConfig
}));

vi.mock('#lib/stores/auth.svelte.js', () => ({
	authStore: mockAuth
}));

vi.mock('#lib/stores/namespace.svelte.js', () => ({
	initNamespace: (...args: unknown[]) => mockInitNamespace(...args),
	isNamespaceReady: () => namespaceStatus === 'ready',
	getNamespaceStatus: () => namespaceStatus,
	getNamespaceError: () => (namespaceStatus === 'failed' ? namespaceError : null)
}));

const { AppBootstrap } = await import('./app-bootstrap.svelte');

describe('AppBootstrap', () => {
	let bootstrap: InstanceType<typeof AppBootstrap>;

	beforeEach(() => {
		vi.clearAllMocks();
		mockConfig.config = null;
		mockConfig.error = null;
		mockConfig.authRequired = true;
		mockConfig.settled = false;
		mockAuth.status = 'unknown';
		mockAuth.error = null;
		mockAuth.authenticated = false;
		mockAuth.bootstrapFailed = false;
		namespaceStatus = 'pending';
		namespaceError = null;
		mockFetch.mockImplementation(async () => {
			mockConfig.config = { auth_required: true, default_namespace: 'default' };
			mockConfig.settled = true;
		});
		mockResolve.mockImplementation(async () => {
			mockAuth.status = 'authenticated';
			mockAuth.authenticated = true;
		});
		mockInitNamespace.mockImplementation(async () => {
			namespaceStatus = 'ready';
		});
		bootstrap = new AppBootstrap();
	});

	test('start fetches config and auth in parallel then initializes namespace', async () => {
		const order: string[] = [];
		mockFetch.mockImplementation(async () => {
			order.push('config-start');
			await Promise.resolve();
			mockConfig.config = { auth_required: true, default_namespace: 'default' };
			mockConfig.settled = true;
			order.push('config-end');
		});
		mockResolve.mockImplementation(async () => {
			order.push('auth-start');
			await Promise.resolve();
			mockAuth.status = 'authenticated';
			mockAuth.authenticated = true;
			order.push('auth-end');
		});
		mockInitNamespace.mockImplementation(async () => {
			order.push('namespace');
			namespaceStatus = 'ready';
		});

		await bootstrap.start();

		expect(order.indexOf('config-start')).toBeLessThan(order.indexOf('namespace'));
		expect(order.indexOf('auth-start')).toBeLessThan(order.indexOf('namespace'));
		expect(order).toContain('namespace');
		expect(bootstrap.appReady).toBe(true);
		expect(bootstrap.phase(false)).toBe('app');
	});

	test('start is idempotent', async () => {
		await bootstrap.start();
		await bootstrap.start();
		await bootstrap.retry();
		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(mockResolve).toHaveBeenCalledTimes(1);
		expect(mockInitNamespace).toHaveBeenCalledTimes(1);
	});

	test('retry recovers a failed configuration probe', async () => {
		mockFetch
			.mockImplementationOnce(async () => {
				mockConfig.config = null;
				mockConfig.error = 'config down';
				mockConfig.settled = true;
			})
			.mockImplementationOnce(async () => {
				mockConfig.config = { auth_required: true, default_namespace: 'default' };
				mockConfig.error = null;
				mockConfig.settled = true;
			});

		await bootstrap.start();
		expect(bootstrap.phase(false)).toBe('error');
		expect(bootstrap.error).toBe('config down');

		await bootstrap.retry();

		expect(bootstrap.appReady).toBe(true);
		expect(bootstrap.phase(false)).toBe('app');
		expect(bootstrap.error).toBeNull();
		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(mockInitNamespace).toHaveBeenCalledTimes(1);
	});

	test('retry during initial bootstrap joins the startup attempt', async () => {
		const configStart = createDeferred<void>();
		mockFetch.mockImplementationOnce(async () => {
			await configStart.promise;
			mockConfig.config = { auth_required: true, default_namespace: 'default' };
			mockConfig.error = null;
			mockConfig.settled = true;
		});

		const startup = bootstrap.start();
		const retry = bootstrap.retry();
		await Promise.resolve();

		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(mockResolve).toHaveBeenCalledTimes(1);
		expect(bootstrap.retrying).toBe(true);

		configStart.resolve();
		await Promise.all([startup, retry]);

		expect(mockInitNamespace).toHaveBeenCalledTimes(1);
		expect(bootstrap.appReady).toBe(true);
	});

	test('concurrent retries join the same in-flight attempt', async () => {
		mockFetch.mockImplementationOnce(async () => {
			mockConfig.config = null;
			mockConfig.error = 'config down';
			mockConfig.settled = true;
		});
		const configRetry = createDeferred<void>();
		mockFetch.mockImplementationOnce(async () => {
			await configRetry.promise;
			mockConfig.config = { auth_required: true, default_namespace: 'default' };
			mockConfig.error = null;
			mockConfig.settled = true;
		});

		await bootstrap.start();
		const firstRetry = bootstrap.retry();
		const secondRetry = bootstrap.retry();
		await Promise.resolve();

		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(mockResolve).toHaveBeenCalledTimes(2);
		expect(bootstrap.retrying).toBe(true);

		configRetry.resolve();
		await Promise.all([firstRetry, secondRetry]);

		expect(mockInitNamespace).toHaveBeenCalledTimes(1);
		expect(bootstrap.retrying).toBe(false);
		expect(bootstrap.appReady).toBe(true);
	});

	test('repeated retry failures keep the latest error actionable', async () => {
		mockFetch
			.mockImplementationOnce(async () => {
				mockConfig.config = null;
				mockConfig.error = 'first failure';
				mockConfig.settled = true;
			})
			.mockImplementationOnce(async () => {
				mockConfig.config = null;
				mockConfig.error = 'second failure';
				mockConfig.settled = true;
			})
			.mockImplementationOnce(async () => {
				mockConfig.config = { auth_required: true, default_namespace: 'default' };
				mockConfig.error = null;
				mockConfig.settled = true;
			});

		await bootstrap.start();
		expect(bootstrap.error).toBe('first failure');

		await bootstrap.retry();
		expect(bootstrap.error).toBe('second failure');
		expect(bootstrap.retrying).toBe(false);

		await bootstrap.retry();
		expect(bootstrap.appReady).toBe(true);
		expect(bootstrap.error).toBeNull();
		expect(mockFetch).toHaveBeenCalledTimes(3);
	});

	test('retry re-runs failed namespace initialization without clearing auth', async () => {
		mockInitNamespace
			.mockImplementationOnce(async () => {
				namespaceStatus = 'failed';
				namespaceError = 'namespace unavailable';
			})
			.mockImplementationOnce(async () => {
				namespaceStatus = 'ready';
				namespaceError = null;
			});

		await bootstrap.start();
		expect(bootstrap.error).toBe('namespace unavailable');
		expect(mockAuth.authenticated).toBe(true);

		await bootstrap.retry();

		expect(bootstrap.appReady).toBe(true);
		expect(mockAuth.authenticated).toBe(true);
		expect(mockInitNamespace).toHaveBeenCalledTimes(2);
	});

	test('skips namespace when config fails', async () => {
		mockFetch.mockImplementation(async () => {
			mockConfig.config = null;
			mockConfig.error = 'config down';
			mockConfig.settled = true;
		});

		await bootstrap.start();

		expect(mockInitNamespace).not.toHaveBeenCalled();
		expect(bootstrap.phase(false)).toBe('error');
		expect(bootstrap.error).toBe('config down');
	});

	test('auth pages only need config', async () => {
		mockFetch.mockImplementation(async () => {
			mockConfig.config = { auth_required: true };
			mockConfig.settled = true;
		});
		mockResolve.mockImplementation(async () => {
			mockAuth.status = 'failed';
			mockAuth.bootstrapFailed = true;
			mockAuth.error = 'session probe failed';
		});

		await bootstrap.start();

		expect(bootstrap.phase(true)).toBe('auth');
		expect(bootstrap.errorFor(true)).toBeNull();
		expect(bootstrap.phase(false)).toBe('error');
		expect(bootstrap.errorFor(false)).toMatch(/session/i);
	});

	test('surfaces namespace failure on app routes', async () => {
		mockInitNamespace.mockImplementation(async () => {
			namespaceStatus = 'failed';
			namespaceError = 'Configuration is missing default_namespace';
		});

		await bootstrap.start();

		expect(bootstrap.phase(false)).toBe('error');
		expect(bootstrap.error).toBe('Configuration is missing default_namespace');
	});

	test('unauthenticated with auth required is app-ready (redirect handled by layout)', async () => {
		mockResolve.mockImplementation(async () => {
			mockAuth.status = 'unauthenticated';
			mockAuth.authenticated = false;
		});
		mockInitNamespace.mockImplementation(async () => {
			namespaceStatus = 'ready';
		});

		await bootstrap.start();

		expect(bootstrap.appReady).toBe(true);
		expect(bootstrap.phase(false)).toBe('app');
	});

	test('loading until start settles', () => {
		expect(bootstrap.phase(false)).toBe('loading');
		expect(bootstrap.phase(true)).toBe('auth');
	});
});
