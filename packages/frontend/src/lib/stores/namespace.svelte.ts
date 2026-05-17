import { idbGet, idbSet, idbDelete } from '$lib/utils/indexeddb';
import { configStore } from '$lib/stores/config.svelte';

const NAMESPACE_KEY = 'namespace';

function isValid(value: unknown): value is string {
	return typeof value === 'string' && value.trim().length > 0;
}

let namespace = $state<string>('');
let ready = $state(false);
let switching = $state(false);
let pending: Promise<void> | null = null;

export async function initNamespace(): Promise<void> {
	if (isValid(namespace)) {
		ready = true;
		return;
	}
	if (pending) return pending;

	pending = (async () => {
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
			throw new Error('Default namespace missing from config');
		}
		namespace = configStore.config.default_namespace;
		await idbSet(NAMESPACE_KEY, namespace);
		ready = true;
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
		namespace = '';
		ready = false;
		await idbDelete(NAMESPACE_KEY);
		return;
	}
	namespace = value;
	ready = true;
	await idbSet(NAMESPACE_KEY, value);
}

export async function switchNamespace(
	value: string,
	hooks?: { beforeCommit?: () => void | Promise<void>; afterCommit?: () => void | Promise<void> }
): Promise<void> {
	switching = true;
	try {
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
