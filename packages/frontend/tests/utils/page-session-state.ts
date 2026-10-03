import type { BrowserContext } from '@playwright/test';
import type { E2EStorageState } from './api.js';

const cleanupSessionStates = new WeakMap<BrowserContext, E2EStorageState>();

export function rememberCleanupSessionState(
	context: BrowserContext,
	storageState: E2EStorageState
): void {
	cleanupSessionStates.set(context, structuredClone(storageState));
}

export function getCleanupSessionState(context: BrowserContext): E2EStorageState | undefined {
	const storageState = cleanupSessionStates.get(context);
	return storageState ? structuredClone(storageState) : undefined;
}
