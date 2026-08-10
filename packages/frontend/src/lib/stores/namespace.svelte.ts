import { registerNamespace } from '$lib/api/namespaces';
import { idbGet, idbSet, idbDelete } from '$lib/utils/indexeddb';
import { configStore } from '$lib/stores/config.svelte';

const NAMESPACE_KEY = 'namespace';

/** Lifecycle of the active namespace — same shape as auth: terminal success or failure. */
export type NamespaceStatus = 'pending' | 'ready' | 'failed';

function isValid(value: unknown): value is string {
	return typeof value === 'string' && value.trim().length > 0;
}

let namespace = $state<string>('');
let status = $state<NamespaceStatus>('pending');
let error = $state<string | null>(null);
let switching = $state(false);
let pending: Promise<void> | null = null;

function invalidateNamespaceRequests(): void {
	if (typeof window !== 'undefined') {
		window.dispatchEvent(new Event('dataforge:namespace-will-change'));
	}
}

function markReady(value: string): void {
	namespace = value;
	status = 'ready';
	error = null;
}

function markFailed(message: string): void {
	namespace = '';
	status = 'failed';
	error = message;
}

function markPending(): void {
	status = 'pending';
	error = null;
}

export function isNamespaceReady(): boolean {
	return status === 'ready' && isValid(namespace);
}

export function isNamespaceSwitching(): boolean {
	return switching;
}

export function getNamespaceStatus(): NamespaceStatus {
	return status;
}

export function getNamespaceError(): string | null {
	return status === 'failed' ? error : null;
}

/**
 * Resolve the active namespace once per app load.
 *
 * Success: stored value, or config.default_namespace.
 * Failure: terminal `failed` status — never leave callers on `pending` forever,
 * and never throw out of fire-and-forget layout effects.
 */
export async function initNamespace(): Promise<void> {
	if (status === 'ready' && isValid(namespace)) return;
	if (pending) return pending;

	pending = (async () => {
		markPending();

		const stored = await idbGet<string>(NAMESPACE_KEY);
		if (isValid(stored)) {
			markReady(stored);
			return;
		}
		if (stored !== null) {
			await idbDelete(NAMESPACE_KEY);
		}

		await configStore.fetch();
		const defaultNamespace = configStore.config?.default_namespace;
		if (!isValid(defaultNamespace)) {
			// Config itself failed, or config loaded without a default — both are
			// contract failures for namespace selection. Layout already prefers
			// configStore.error when present; this status is for "config ok but
			// unusable" and for callers that only observe namespace.
			markFailed(
				configStore.config
					? 'Configuration is missing default_namespace'
					: (configStore.error ?? 'Configuration is unavailable')
			);
			return;
		}

		await idbSet(NAMESPACE_KEY, defaultNamespace);
		markReady(defaultNamespace);
	})();

	try {
		await pending;
	} finally {
		pending = null;
	}
}

export function requireNamespace(): string {
	if (status !== 'ready' || !isValid(namespace)) {
		throw new Error('Namespace not initialized — call initNamespace() first');
	}
	return namespace;
}

export async function setNamespace(value: string): Promise<void> {
	if (!isValid(value)) {
		if (namespace) invalidateNamespaceRequests();
		namespace = '';
		markPending();
		await idbDelete(NAMESPACE_KEY);
		return;
	}
	if (value === namespace && status === 'ready') return;
	invalidateNamespaceRequests();
	await idbSet(NAMESPACE_KEY, value);
	markReady(value);
}

export async function switchNamespace(
	value: string,
	hooks?: { beforeCommit?: () => void | Promise<void>; afterCommit?: () => void | Promise<void> }
): Promise<void> {
	switching = true;
	try {
		if (isValid(value)) {
			const result = await registerNamespace(value);
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
		}
		await hooks?.beforeCommit?.();
		await setNamespace(value);
		await hooks?.afterCommit?.();
	} finally {
		switching = false;
	}
}

export const useNamespace = () => ({
	get value() {
		return requireNamespace();
	},
	get ready() {
		return isNamespaceReady();
	},
	get status() {
		return status;
	},
	get error() {
		return getNamespaceError();
	},
	get switching() {
		return switching;
	},
	async set(value: string) {
		await setNamespace(value);
	}
});
