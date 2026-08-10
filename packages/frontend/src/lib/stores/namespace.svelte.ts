import { registerNamespace } from '$lib/api/namespaces';
import { idbGet, idbSet, idbDelete } from '$lib/utils/indexeddb';
import { configStore } from '$lib/stores/config.svelte';

const NAMESPACE_KEY = 'namespace';

function isValid(value: unknown): value is string {
	return typeof value === 'string' && value.trim().length > 0;
}

let namespace = $state<string>('');
let ready = $state(false);
let switching = $state(false);
let initError = $state<string | null>(null);
let pending: Promise<void> | null = null;

function invalidateNamespaceRequests(): void {
	if (typeof window !== 'undefined') {
		window.dispatchEvent(new Event('dataforge:namespace-will-change'));
	}
}

export function getNamespaceInitError(): string | null {
	return initError;
}

export async function initNamespace(): Promise<void> {
	if (isValid(namespace)) {
		ready = true;
		initError = null;
		return;
	}
	if (pending) return pending;

	pending = (async () => {
		initError = null;
		const stored = await idbGet<string>(NAMESPACE_KEY);
		if (isValid(stored)) {
			namespace = stored;
			ready = true;
			return;
		}
		if (stored !== null) {
			await idbDelete(NAMESPACE_KEY);
		}
		await configStore.fetch();
		if (!isValid(configStore.config?.default_namespace)) {
			// Surface as state so layout can leave the spinner. Do not throw —
			// callers use void initNamespace() and an unhandled rejection left
			// the shell permanently blank.
			ready = false;
			initError =
				configStore.error ??
				'Default namespace missing from config. Check that the API is reachable.';
			return;
		}
		namespace = configStore.config.default_namespace;
		await idbSet(NAMESPACE_KEY, namespace);
		ready = true;
		initError = null;
	})();

	try {
		await pending;
	} finally {
		pending = null;
	}
}

export function requireNamespace(): string {
	if (!ready || !isValid(namespace)) {
		throw new Error('Namespace not initialized — call initNamespace() first');
	}
	return namespace;
}

export function isNamespaceReady(): boolean {
	return ready;
}

export function isNamespaceSwitching(): boolean {
	return switching;
}

export async function setNamespace(value: string): Promise<void> {
	if (!isValid(value)) {
		if (namespace) invalidateNamespaceRequests();
		namespace = '';
		ready = false;
		initError = null;
		await idbDelete(NAMESPACE_KEY);
		return;
	}
	if (value === namespace && ready) return;
	invalidateNamespaceRequests();
	namespace = value;
	ready = true;
	initError = null;
	await idbSet(NAMESPACE_KEY, value);
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
		return ready;
	},
	get switching() {
		return switching;
	},
	async set(value: string) {
		await setNamespace(value);
	}
});
