import { authStore } from '$lib/stores/auth.svelte';
import { configStore } from '$lib/stores/config.svelte';
import {
	getNamespaceError,
	getNamespaceStatus,
	initNamespace,
	isNamespaceReady
} from '$lib/stores/namespace.svelte';

/**
 * What the root layout should render after bootstrap is considered.
 *
 * - loading: still waiting on a required probe
 * - error: terminal failure with a user-visible message
 * - auth: config is good; show login/register (session not required)
 * - app: full shell (config + namespace + session when auth is required)
 */
export type ShellPhase = 'loading' | 'error' | 'auth' | 'app';

/**
 * Owns the app cold-start sequence. Individual stores still hold their domain
 * state; this service is the single orchestrator and the single place layout
 * asks "what should I show?"
 *
 * Order:
 *  1. Config + session probe in parallel (both bounded by bootstrap timeouts)
 *  2. Namespace after config has settled (needs default_namespace or IDB)
 */
export class AppBootstrap {
	private run: Promise<void> | null = null;
	/** True after start() has finished its orchestration attempt. */
	private settled = $state(false);

	/**
	 * Kick bootstrap exactly once. Safe to call from a layout $effect.
	 */
	start(): Promise<void> {
		if (this.run) return this.run;

		this.run = (async () => {
			// Config and session are independent; fail independently.
			await Promise.all([configStore.fetch(), authStore.resolve()]);

			// Namespace depends on config (or a prior IDB value). Skip when config
			// is unusable so we don't invent a second error for the same outage.
			if (configStore.config !== null) {
				await initNamespace();
			}
		})().finally(() => {
			this.settled = true;
		});

		return this.run;
	}

	/** Full application shell may mount. */
	get appReady(): boolean {
		if (configStore.config === null) return false;
		if (!isNamespaceReady()) return false;
		if (!configStore.authRequired) return true;
		if (authStore.bootstrapFailed) return false;
		return authStore.authenticated || authStore.status === 'unauthenticated';
	}

	/**
	 * Terminal bootstrap failure message for the full app shell, or null while
	 * still loading / when healthy. Auth routes use {@link phase} instead.
	 */
	get error(): string | null {
		if (configStore.error) return configStore.error;
		if (this.settled && configStore.config === null) {
			return 'Failed to load application configuration';
		}
		if (configStore.authRequired && authStore.bootstrapFailed) {
			return authStore.error ?? 'Failed to verify session';
		}
		if (getNamespaceStatus() === 'failed') {
			return getNamespaceError();
		}
		return null;
	}

	/**
	 * Resolve the shell view for the current route class.
	 *
	 * Auth pages only require config. App pages require full readiness.
	 */
	phase(onAuthPage: boolean): ShellPhase {
		if (onAuthPage) {
			if (configStore.config !== null) return 'auth';
			if (configStore.error || (this.settled && configStore.config === null)) return 'error';
			return 'loading';
		}

		if (this.appReady) return 'app';
		if (this.error) return 'error';
		return 'loading';
	}

	/** Error message for the current phase (auth or app). */
	errorFor(onAuthPage: boolean): string | null {
		if (onAuthPage) {
			if (configStore.error) return configStore.error;
			if (this.settled && configStore.config === null) {
				return 'Failed to load application configuration';
			}
			return null;
		}
		return this.error;
	}
}

export const appBootstrap = new AppBootstrap();
