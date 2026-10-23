import { getMe, login, logout, register, updateProfile, type UserPublic } from '#lib/api/auth.js';

type AuthStatus = 'unknown' | 'authenticated' | 'unauthenticated' | 'failed';

export class AuthStore {
	user = $state<UserPublic | null>(null);
	status = $state<AuthStatus>('unknown');
	loading = $state(false);
	error = $state<string | null>(null);
	private operationVersion = 0;
	private resolvePending: Promise<void> | null = null;

	private beginOperation(): number {
		const version = ++this.operationVersion;
		this.loading = true;
		this.error = null;
		return version;
	}

	private finishOperation(version: number): void {
		if (version === this.operationVersion) this.loading = false;
	}

	get authenticated(): boolean {
		return this.status === 'authenticated' && this.user !== null;
	}

	/** Auth has a terminal answer for bootstrap (including hard failure). */
	get resolved(): boolean {
		return this.status !== 'unknown';
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
			this.finishOperation(version);
		});

		this.resolvePending = request;
		return request;
	}

	async login(email: string, password: string): Promise<boolean> {
		const version = this.beginOperation();
		const result = await login({ email, password });
		if (version !== this.operationVersion) return false;
		let success = false;
		result.match(
			(user) => {
				this.user = user;
				this.status = 'authenticated';
				success = true;
			},
			(err) => {
				this.error = err.message;
			}
		);
		this.finishOperation(version);
		return success;
	}

	async register(email: string, password: string, name: string): Promise<boolean> {
		const version = this.beginOperation();
		const result = await register({ email, password, display_name: name });
		if (version !== this.operationVersion) return false;
		let success = false;
		result.match(
			(user) => {
				this.user = user;
				this.status = 'authenticated';
				success = true;
			},
			(err) => {
				this.error = err.message;
			}
		);
		this.finishOperation(version);
		return success;
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
		let success = false;
		result.match(
			(user) => {
				this.user = user;
				success = true;
			},
			(err) => {
				this.error = err.message;
			}
		);
		this.finishOperation(version);
		return success;
	}

	clear(): void {
		this.operationVersion += 1;
		this.user = null;
		this.status = 'unauthenticated';
		this.error = null;
	}
}

export const authStore = new AuthStore();
