import { describe, test, expect, vi, beforeEach } from 'vitest';
import type { UserPublic } from '$lib/api/auth';

const mockGetMe = vi.fn();
const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockRegister = vi.fn();
const mockUpdateProfile = vi.fn();

vi.mock('$lib/api/auth', () => ({
	getMe: (...args: unknown[]) => mockGetMe(...args),
	login: (...args: unknown[]) => mockLogin(...args),
	logout: (...args: unknown[]) => mockLogout(...args),
	register: (...args: unknown[]) => mockRegister(...args),
	updateProfile: (...args: unknown[]) => mockUpdateProfile(...args)
}));

const { AuthStore } = await import('./auth.svelte');

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
		match: (onOk: (u: UserPublic) => void, _onErr: (e: { message: string }) => void) => {
			onOk(user);
			return Promise.resolve();
		}
	});
}

function mockMeError(message: string) {
	mockGetMe.mockReturnValue({
		match: (_onOk: unknown, onErr: (e: { message: string }) => void) => {
			onErr({ message });
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

		test('failure sets unauthenticated', async () => {
			mockMeError('Unauthorized');

			await store.resolve();

			expect(store.status).toBe('unauthenticated');
			expect(store.user).toBeNull();
			expect(store.authenticated).toBe(false);
			expect(store.resolved).toBe(true);
		});

		test('second resolve is a no-op', async () => {
			mockMeSuccess(makeUser());
			await store.resolve();
			expect(mockGetMe).toHaveBeenCalledTimes(1);

			await store.resolve();
			expect(mockGetMe).toHaveBeenCalledTimes(1);
		});
	});

	describe('resolve always resolves on failure', () => {
		test('failure sets unauthenticated', async () => {
			mockMeError('Network error');

			await store.resolve();

			expect(store.status).toBe('unauthenticated');
			expect(store.user).toBeNull();
			expect(store.resolved).toBe(true);
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
