import fs from 'node:fs';
import type { Page, APIRequestContext } from '@playwright/test';
import { test as base } from '@playwright/test';
import {
	AUTH_DIR,
	buildStorageState,
	deleteAccount,
	ensureWorkerClean,
	readMeta,
	readStoredSessionToken,
	registerWorker,
	workerAuthFile
} from './utils/api.js';

export { expect } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;

interface WorkerAuth {
	authFile: string;
	workerIndex: number;
}

async function ensureAuthFileReady(workerAuth: WorkerAuth): Promise<void> {
	if (fs.existsSync(workerAuth.authFile)) return;
	const meta = readMeta();
	const token = meta.authRequired ? await registerWorker(workerAuth.workerIndex) : undefined;
	fs.mkdirSync(AUTH_DIR, { recursive: true });
	fs.writeFileSync(workerAuth.authFile, JSON.stringify(buildStorageState(token), null, 2));
}

export const test = base.extend<
	{ page: Page; request: APIRequestContext },
	{ workerAuth: WorkerAuth }
>({
	workerAuth: [
		// Hybrid suite setup: auth is provisioned via API so browser tests can focus on feature flows.
		// eslint-disable-next-line no-empty-pattern
		async ({}, use, workerInfo) => {
			const idx = workerInfo.workerIndex;
			const authFile = workerAuthFile(idx);

			fs.mkdirSync(AUTH_DIR, { recursive: true });

			const meta = readMeta();

			if (meta.authRequired) {
				await ensureWorkerClean(idx);
				const token = await registerWorker(idx);
				fs.writeFileSync(authFile, JSON.stringify(buildStorageState(token), null, 2));
			} else {
				fs.writeFileSync(authFile, JSON.stringify(buildStorageState(undefined), null, 2));
			}

			await use({ authFile, workerIndex: idx });

			if (meta.authRequired) {
				const token = readStoredSessionToken(authFile);
				if (token) {
					await deleteAccount(token).catch(() => {});
				}
			}
		},
		{ scope: 'worker' }
	],

	page: async ({ browser, workerAuth }, use) => {
		await ensureAuthFileReady(workerAuth);
		const context = await browser.newContext({
			baseURL,
			storageState: workerAuth.authFile
		});
		const page = await context.newPage();
		await use(page);
		await page.close({ runBeforeUnload: true });
		await context.close();
	},

	request: async ({ playwright, workerAuth }, use) => {
		await ensureAuthFileReady(workerAuth);
		const token = readStoredSessionToken(workerAuth.authFile);
		const ctx = await playwright.request.newContext({
			baseURL,
			storageState: workerAuth.authFile,
			extraHTTPHeaders: token ? { 'X-Session-Token': token } : undefined
		});
		await use(ctx);
		await ctx.dispose();
	}
});
