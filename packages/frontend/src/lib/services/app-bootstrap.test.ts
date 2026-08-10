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

vi.mock('$lib/stores/config.svelte', () => ({
	configStore: mockConfig
}));

vi.mock('$lib/stores/auth.svelte', () => ({
	authStore: mockAuth
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
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
		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(mockResolve).toHaveBeenCalledTimes(1);
		expect(mockInitNamespace).toHaveBeenCalledTimes(1);
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
		expect(bootstrap.phase(true)).toBe('loading');
	});
});
