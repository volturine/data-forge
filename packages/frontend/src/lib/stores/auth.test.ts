import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { UserPublic } from '#lib/api/auth.js';

const mockGetMe = vi.fn();
const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockRegister = vi.fn();
const mockUpdateProfile = vi.fn();

vi.mock('#lib/api/auth.js', () => ({
	getMe: (...args: unknown[]) => mockGetMe(...args),
	login: (...args: unknown[]) => mockLogin(...args),
	logout: (...args: unknown[]) => mockLogout(...args),
	register: (...args: unknown[]) => mockRegister(...args),
	updateProfile: (...args: unknown[]) => mockUpdateProfile(...args)
}));

const { AuthStore } = await import('./auth.svelte');

interface MockMeResult {
	match(
		onOk: (user: UserPublic) => void,
		onErr: (error: { message: string; status?: number }) => void
	): Promise<void>;
}

function createDeferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((resolvePromise) => {
		resolve = resolvePromise;
	});
	return { promise, resolve };
}

function makeUser(overrides: Partial<UserPublic> = {}): UserPublic {
	return {
		id: 'user-1',
		email: 'dev@localhost',
		display_name: 'Dev User',
		avatar_url: null,
		status: 'active',
		email_verified: true,
		has_password: false,
		preferences: {},
		providers: [],
		created_at: '2025-01-01T00:00:00Z',
		...overrides
	};
}

function mockMeSuccess(user: UserPublic) {
	mockGetMe.mockReturnValue({
		match: (
			onOk: (u: UserPublic) => void,
			_onErr: (e: { message: string; status?: number }) => void
		) => {
			onOk(user);
			return Promise.resolve();
		}
	} satisfies MockMeResult);
}

function mockMeError(message: string, status?: number) {
	mockGetMe.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string; status?: number }) => void) => {
			onErr({ message, status });
			return Promise.resolve();
		}
	});
}

function mockLoginSuccess(user: UserPublic) {
	mockLogin.mockReturnValue({
		match: (onOk: (u: UserPublic) => void, _onErr: (e: { message: string }) => void) => {
			onOk(user);
			return Promise.resolve();
		}
	});
}

function mockLoginError(message: string) {
	mockLogin.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
			return Promise.resolve();
		}
	});
}

function mockLogoutSuccess() {
	mockLogout.mockReturnValue({
		match: (onOk: (r: { success: boolean }) => void) => {
			onOk({ success: true });
			return Promise.resolve();
		}
	});
}

describe('AuthStore', () => {
	let store: InstanceType<typeof AuthStore>;

	beforeEach(() => {
		vi.clearAllMocks();
		store = new AuthStore();
	});

	describe('initial state', () => {
		test('user is null', () => {
			expect(store.user).toBeNull();
		});

		test('status is unknown', () => {
			expect(store.status).toBe('unknown');
		});

		test('authenticated is false', () => {
			expect(store.authenticated).toBe(false);
		});

		test('resolved is false', () => {
			expect(store.resolved).toBe(false);
		});

		test('loading is false', () => {
			expect(store.loading).toBe(false);
		});
	});

	describe('resolve', () => {
		test('success sets authenticated', async () => {
			const user = makeUser();
			mockMeSuccess(user);

			await store.resolve();

			expect(store.status).toBe('authenticated');
			expect(store.user).toEqual(user);
			expect(store.authenticated).toBe(true);
			expect(store.resolved).toBe(true);
			expect(store.loading).toBe(false);
		});

		test('401 sets unauthenticated', async () => {
			mockMeError('Unauthorized', 401);

			await store.resolve();

			expect(store.status).toBe('unauthenticated');
			expect(store.user).toBeNull();
			expect(store.authenticated).toBe(false);
			expect(store.resolved).toBe(true);
			expect(store.bootstrapFailed).toBe(false);
		});

		test('network failure sets failed bootstrap state', async () => {
			mockMeError('Network error');

			await store.resolve();

			expect(store.status).toBe('failed');
			expect(store.user).toBeNull();
			expect(store.resolved).toBe(true);
			expect(store.bootstrapFailed).toBe(true);
			expect(store.error).toBe('Network error');
		});

		test('second resolve is a no-op', async () => {
			mockMeSuccess(makeUser());
			await store.resolve();
			expect(mockGetMe).toHaveBeenCalledTimes(1);

			await store.resolve();
			expect(mockGetMe).toHaveBeenCalledTimes(1);
		});

		test('unauthenticated resolution is preserved without another probe', async () => {
			mockMeError('Unauthorized', 401);
			await store.resolve();

			await store.resolve();

			expect(store.status).toBe('unauthenticated');
			expect(mockGetMe).toHaveBeenCalledTimes(1);
		});

		test('failed session probe can recover on retry', async () => {
			mockMeError('Network error');
			await store.resolve();
			const user = makeUser();
			mockMeSuccess(user);

			await store.resolve();

			expect(store.status).toBe('authenticated');
			expect(store.user).toEqual(user);
			expect(store.error).toBeNull();
			expect(store.loading).toBe(false);
			expect(mockGetMe).toHaveBeenCalledTimes(2);
		});

		test('concurrent retries share one session probe', async () => {
			mockMeError('Network error');
			await store.resolve();
			const response = createDeferred<MockMeResult>();
			mockGetMe.mockReturnValue(response.promise);

			const firstRetry = store.resolve();
			const secondRetry = store.resolve();
			expect(mockGetMe).toHaveBeenCalledTimes(2);

			response.resolve({
				match: (onOk) => {
					onOk(makeUser());
					return Promise.resolve();
				}
			});
			await Promise.all([firstRetry, secondRetry]);

			expect(store.authenticated).toBe(true);
			expect(store.loading).toBe(false);
			expect(mockGetMe).toHaveBeenCalledTimes(2);
		});

		test('login supersedes a failed-session retry', async () => {
			mockMeError('Network error');
			await store.resolve();
			const response = createDeferred<MockMeResult>();
			mockGetMe.mockReturnValue(response.promise);
			const retry = store.resolve();
			const user = makeUser();
			mockLoginSuccess(user);

			await store.login(user.email, 'password');
			response.resolve({
				match: (_onOk, onErr) => {
					onErr({ message: 'late network failure' });
					return Promise.resolve();
				}
			});
			await retry;

			expect(store.authenticated).toBe(true);
			expect(store.user).toEqual(user);
			expect(store.error).toBeNull();
			expect(store.loading).toBe(false);
		});
	});

	describe('login', () => {
		test('success sets authenticated', async () => {
			const user = makeUser();
			mockLoginSuccess(user);

			const result = await store.login('dev@localhost', 'password');

			expect(result).toBe(true);
			expect(store.status).toBe('authenticated');
			expect(store.user).toEqual(user);
		});

		test('failure sets error', async () => {
			mockLoginError('Invalid credentials');

			const result = await store.login('bad@test', 'wrong');

			expect(result).toBe(false);
			expect(store.error).toBe('Invalid credentials');
			expect(store.authenticated).toBe(false);
		});
	});

	describe('logout', () => {
		test('resets to unauthenticated', async () => {
			mockMeSuccess(makeUser());
			await store.resolve();
			expect(store.authenticated).toBe(true);

			mockLogoutSuccess();
			await store.logout();

			expect(store.status).toBe('unauthenticated');
			expect(store.user).toBeNull();
			expect(store.error).toBeNull();
		});
	});

	describe('clear', () => {
		test('resets state', async () => {
			mockMeSuccess(makeUser());
			await store.resolve();

			store.clear();

			expect(store.user).toBeNull();
			expect(store.status).toBe('unauthenticated');
			expect(store.error).toBeNull();
		});
	});
});
