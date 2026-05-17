import { browser } from '$app/environment';

type DbConfig = {
	name: string;
	store: string;
	version?: number;
};

const defaultConfig: DbConfig = {
	name: 'polars-fastapi-svelte',
	store: 'cache',
	version: 1
};

function openDb(config: DbConfig): Promise<IDBDatabase> {
	if (!browser) return Promise.reject(new Error('IndexedDB not available'));
	return new Promise((resolve, reject) => {
		const request = indexedDB.open(config.name, config.version ?? 1);
		request.onupgradeneeded = () => {
			const db = request.result;
			if (!db.objectStoreNames.contains(config.store)) {
				db.createObjectStore(config.store);
			}
		};
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error ?? new Error('Failed to open IndexedDB'));
	});
}

async function withStore<T>(
	config: DbConfig,
	mode: IDBTransactionMode,
	fn: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
	const db = await openDb(config);
	return new Promise((resolve, reject) => {
		const transaction = db.transaction(config.store, mode);
		const store = transaction.objectStore(config.store);
		const request = fn(store);
		request.onsuccess = () => resolve(request.result as T);
		request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
		transaction.oncomplete = () => db.close();
		transaction.onerror = () => db.close();
	});
}

export async function idbGet<T>(key: string, config: DbConfig = defaultConfig): Promise<T | null> {
	try {
		const result = await withStore<T | undefined>(config, 'readonly', (store) => store.get(key));
		return result ?? null;
	} catch {
		return null;
	}
}

export async function idbSet<T>(
	key: string,
	value: T,
	config: DbConfig = defaultConfig
): Promise<void> {
	try {
		await withStore(config, 'readwrite', (store) => store.put(value, key));
	} catch {
		// Ignore write failures
	}
}

export async function idbDelete(key: string, config: DbConfig = defaultConfig): Promise<void> {
	try {
		await withStore(config, 'readwrite', (store) => store.delete(key));
	} catch {
		// Ignore delete failures
	}
}

export async function idbClear(config: DbConfig = defaultConfig): Promise<void> {
	try {
		await withStore(config, 'readwrite', (store) => store.clear());
	} catch {
		// Ignore clear failures
	}
}

export async function idbEntries<T>(
	config: DbConfig = defaultConfig
): Promise<Array<{ key: string; value: T }>> {
	try {
		const db = await openDb(config);
		return await new Promise((resolve, reject) => {
			const transaction = db.transaction(config.store, 'readonly');
			const store = transaction.objectStore(config.store);
			const entries: Array<{ key: string; value: T }> = [];
			const request = store.openCursor();
			request.onsuccess = () => {
				const cursor = request.result;
				if (!cursor) {
					resolve(entries);
					return;
				}
				entries.push({ key: String(cursor.key), value: cursor.value as T });
				cursor.continue();
			};
			request.onerror = () => reject(request.error ?? new Error('IndexedDB cursor failed'));
			transaction.oncomplete = () => db.close();
			transaction.onerror = () => db.close();
		});
	} catch {
		return [];
	}
}
