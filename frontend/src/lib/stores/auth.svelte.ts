import { getMe, login, logout, register, updateProfile, type UserPublic } from '$lib/api/auth';

type AuthStatus = 'unknown' | 'authenticated' | 'unauthenticated';

export class AuthStore {
	user = $state<UserPublic | null>(null);
	status = $state<AuthStatus>('unknown');
	loading = $state(false);
	error = $state<string | null>(null);

	get authenticated(): boolean {
		return this.status === 'authenticated' && this.user !== null;
	}

	get resolved(): boolean {
		return this.status !== 'unknown';
	}

	async resolve(): Promise<void> {
		if (this.status !== 'unknown') return;
		this.loading = true;
		this.error = null;
		const result = await getMe();
		result.match(
			(user) => {
				this.user = user;
				this.status = 'authenticated';
			},
			() => {
				this.user = null;
				this.status = 'unauthenticated';
			}
		);
		this.loading = false;
	}

	async login(email: string, password: string): Promise<boolean> {
		this.loading = true;
		this.error = null;
		const result = await login({ email, password });
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
		this.loading = false;
		return success;
	}

	async register(email: string, password: string, name: string): Promise<boolean> {
		this.loading = true;
		this.error = null;
		const result = await register({ email, password, display_name: name });
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
		this.loading = false;
		return success;
	}

	async logout(): Promise<void> {
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
		this.loading = true;
		this.error = null;
		const result = await updateProfile(payload);
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
		this.loading = false;
		return success;
	}

	clear(): void {
		this.user = null;
		this.status = 'unauthenticated';
		this.error = null;
	}
}

export const authStore = new AuthStore();
