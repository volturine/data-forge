import { authStore } from '#lib/stores/auth.svelte.js';
import { configStore } from '#lib/stores/config.svelte.js';
import {
	getNamespaceError,
	getNamespaceStatus,
	initNamespace,
	isNamespaceReady
} from '#lib/stores/namespace.svelte.js';

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
	private succeeded = false;
	private lastFailure = $state<string | null>(null);
	retrying = $state(false);
	/** True after the current orchestration attempt has finished. */
	private settled = $state(false);

	/**
	 * Kick bootstrap once. Safe to call from layout `onMount`.
	 */
	start(): Promise<void> {
		if (this.run) return this.run;

		this.settled = false;
		this.retrying = true;
		let unexpectedError: string | null = null;

		const attempt = async (): Promise<void> => {
			// Config and session are independent; wait for both even if one throws,
			// so a retry never overlaps a still-running cold-start probe.
			const probes = await Promise.allSettled([
				Promise.resolve().then(() => configStore.fetch()),
				Promise.resolve().then(() => authStore.resolve())
			]);
			const failedProbe = probes.find((probe) => probe.status === 'rejected');
			if (failedProbe?.status === 'rejected') {
				unexpectedError = getErrorMessage(failedProbe.reason);
			}

			// Namespace depends on config (or a prior IDB value). Skip when config
			// is unusable so we don't invent a second error for the same outage.
			if (configStore.config === null) return;

			const [namespaceResult] = await Promise.allSettled([
				Promise.resolve().then(() => initNamespace())
			]);
			if (namespaceResult.status === 'rejected') {
				unexpectedError ??= getErrorMessage(namespaceResult.reason);
			}
		};

		this.run = attempt().finally(() => {
			this.settled = true;
			this.succeeded = this.appReady;
			this.lastFailure = this.succeeded
				? null
				: (this.currentError() ?? unexpectedError ?? 'Failed to start application');
			this.retrying = false;
		});

		return this.run;
	}

	/** Retry the last attempt only after it failed; concurrent callers join it. */
	retry(): Promise<void> {
		if (this.run && (!this.settled || this.succeeded)) return this.run;

		this.run = null;
		return this.start();
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
		return this.lastFailure ?? this.currentError();
	}

	private currentError(): string | null {
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
			// Public auth routes are useful before the optional app bootstrap
			// probes settle. Login, reset-password, and verify-email must not
			// render a blank page while config or session discovery is slow.
			return 'auth';
		}

		if (this.appReady) return 'app';
		if (this.error) return 'error';
		return 'loading';
	}

	/** Error message for the current phase (auth or app). */
	errorFor(onAuthPage: boolean): string | null {
		if (onAuthPage) {
			return null;
		}
		return this.error;
	}
}

function getErrorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

export const appBootstrap = new AppBootstrap();
