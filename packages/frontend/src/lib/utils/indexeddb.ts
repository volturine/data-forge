import { browser } from '$app/env';

const dbConfig = {
	// Legacy database name from the project's original codename. Kept so existing
	// browsers keep their stored client identity and cache state; renaming would
	// orphan every user's local data.
	name: 'polars-fastapi-svelte',
	store: 'cache',
	version: 1
};

function openDb(): Promise<IDBDatabase> {
	if (!browser) return Promise.reject(new Error('IndexedDB not available'));
	return new Promise((resolve, reject) => {
		const request = indexedDB.open(dbConfig.name, dbConfig.version);
		request.onupgradeneeded = () => {
			const db = request.result;
			if (!db.objectStoreNames.contains(dbConfig.store)) {
				db.createObjectStore(dbConfig.store);
			}
		};
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error ?? new Error('Failed to open IndexedDB'));
	});
}

async function withStore<T>(
	mode: IDBTransactionMode,
	fn: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
	const db = await openDb();
	return new Promise((resolve, reject) => {
		const transaction = db.transaction(dbConfig.store, mode);
		const store = transaction.objectStore(dbConfig.store);
		const request = fn(store);
		let result: T;
		let settled = false;
		const fail = (error: unknown) => {
			if (settled) return;
			settled = true;
			db.close();
			reject(error instanceof Error ? error : new Error('IndexedDB transaction failed'));
		};

		request.onsuccess = () => {
			result = request.result as T;
		};
		request.onerror = () => {
			fail(request.error ?? new Error('IndexedDB request failed'));
		};
		// A request's success event only means the operation was accepted by the
		// transaction. Resolve after `complete` so callers that navigate or reload
		// immediately after idbSet cannot observe the previous value.
		transaction.oncomplete = () => {
			if (settled) return;
			settled = true;
			db.close();
			resolve(result);
		};
		transaction.onerror = () => {
			fail(transaction.error ?? new Error('IndexedDB transaction failed'));
		};
		transaction.onabort = () => {
			fail(transaction.error ?? new Error('IndexedDB transaction aborted'));
		};
	});
}

export async function idbGet<T>(key: string): Promise<T | null> {
	try {
		const result = await withStore<T | undefined>('readonly', (store) => store.get(key));
		return result ?? null;
	} catch {
		return null;
	}
}

export async function idbSet<T>(key: string, value: T): Promise<void> {
	try {
		await withStore('readwrite', (store) => store.put(value, key));
	} catch {
		// Ignore write failures
	}
}

export async function idbDelete(key: string): Promise<void> {
	try {
		await withStore('readwrite', (store) => store.delete(key));
	} catch {
		// Ignore delete failures
	}
}

export async function idbClear(): Promise<void> {
	try {
		await withStore('readwrite', (store) => store.clear());
	} catch {
		// Ignore clear failures
	}
}

export async function idbEntries<T>(): Promise<Array<{ key: string; value: T }>> {
	try {
		const db = await openDb();
		return await new Promise((resolve, reject) => {
			const transaction = db.transaction(dbConfig.store, 'readonly');
			const store = transaction.objectStore(dbConfig.store);
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
