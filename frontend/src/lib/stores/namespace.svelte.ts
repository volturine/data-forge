import { idbGet, idbSet } from '$lib/utils/indexeddb';
import { configStore } from '$lib/stores/config.svelte';

const NAMESPACE_KEY = 'namespace';

let namespace = $state<string>('');

export async function initNamespace(): Promise<void> {
	if (namespace) return;
	const stored = await idbGet<string>(NAMESPACE_KEY);
	if (stored) {
		namespace = stored;
		return;
	}
	await configStore.fetch();
	namespace = configStore.config?.default_namespace ?? 'default';
	void idbSet(NAMESPACE_KEY, namespace);
}

export function getNamespace(): string {
	return namespace || configStore.config?.default_namespace || 'default';
}

export async function setNamespace(value: string): Promise<void> {
	namespace = value;
	await idbSet(NAMESPACE_KEY, value);
}

export const useNamespace = () => ({
	get value() {
		return getNamespace();
	},
	async set(value: string) {
		await setNamespace(value);
	}
});
