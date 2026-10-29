import { getMe, login, logout, register, updateProfile, type UserPublic } from '#lib/api/auth.js';
import type { ApiError } from '#lib/api/client.js';
import type { Result } from 'neverthrow';

type AuthStatus = 'unknown' | 'authenticated' | 'unauthenticated' | 'failed';

export class AuthStore {
	user = $state<UserPublic | null>(null);
	status = $state<AuthStatus>('unknown');
	error = $state<string | null>(null);
	private operationVersion = 0;
	private resolvePending: Promise<void> | null = null;

	private beginOperation(): number {
		const version = ++this.operationVersion;
		this.error = null;
		return version;
	}

	private settleUserResult(result: Result<UserPublic, ApiError>, authenticated: boolean): boolean {
		let success = false;
		result.match(
			(user) => {
				this.user = user;
				if (authenticated) this.status = 'authenticated';
				success = true;
			},
			(err) => {
				this.error = err.message;
			}
		);
		return success;
	}

	get authenticated(): boolean {
		return this.status === 'authenticated' && this.user !== null;
	}

	/** Bootstrap cannot proceed: session probe failed without a clear 401. */
	get bootstrapFailed(): boolean {
		return this.status === 'failed';
	}

	resolve(): Promise<void> {
		if (this.resolvePending) return this.resolvePending;
		if (this.status !== 'unknown' && !this.bootstrapFailed) return Promise.resolve();

		const version = this.beginOperation();
		const request = (async () => {
			const result = await getMe();
			// A public auth form may be submitted while this optional session probe
			// is in flight. Never let its late response overwrite that operation.
			if (version !== this.operationVersion) return;
			result.match(
				(user) => {
					this.user = user;
					this.status = 'authenticated';
					this.error = null;
				},
				(err) => {
					this.user = null;
					// Unauthenticated session is a normal terminal state. Network /
					// timeout / 5xx leave bootstrap in a failed state for retry.
					if (err.status === 401 || err.status === 403) {
						this.status = 'unauthenticated';
						this.error = null;
					} else {
						this.status = 'failed';
						this.error = err.message;
					}
				}
			);
		})().finally(() => {
			if (this.resolvePending === request) this.resolvePending = null;
		});

		this.resolvePending = request;
		return request;
	}

	async login(email: string, password: string): Promise<boolean> {
		const version = this.beginOperation();
		const result = await login({ email, password });
		if (version !== this.operationVersion) return false;
		return this.settleUserResult(result, true);
	}

	async register(email: string, password: string, name: string): Promise<boolean> {
		const version = this.beginOperation();
		const result = await register({ email, password, display_name: name });
		if (version !== this.operationVersion) return false;
		return this.settleUserResult(result, true);
	}

	async logout(): Promise<void> {
		this.operationVersion += 1;
		await logout();
		this.user = null;
		this.status = 'unauthenticated';
		this.error = null;
	}

	async updateProfile(payload: {
		display_name?: string;
		avatar_url?: string | null;
		preferences?: Record<string, unknown>;
	}): Promise<boolean> {
		const version = this.beginOperation();
		const result = await updateProfile(payload);
		if (version !== this.operationVersion) return false;
		return this.settleUserResult(result, false);
	}
}

export const authStore = new AuthStore();
