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
const baseURL = `http://localhost:${port}`;

interface WorkerAuth {
	authFile: string;
	workerIndex: number;
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
		const context = await browser.newContext({
			baseURL,
			storageState: workerAuth.authFile
		});
		const page = await context.newPage();
		await use(page);
		await page.close();
		await context.close();
	},

	request: async ({ playwright, workerAuth }, use) => {
		const ctx = await playwright.request.newContext({
			baseURL,
			storageState: workerAuth.authFile
		});
		await use(ctx);
		await ctx.dispose();
	}
});
