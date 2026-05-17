import fs from 'node:fs';
import path from 'node:path';
import type { Browser, Page } from '@playwright/test';
import { expect, test as base } from '@playwright/test';
import { E2E_PASSWORD, E2E_RUN_STAMP, type E2ERequest, workerAuthFile } from './utils/api.js';

export { expect } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
const authRequired = process.env.AUTH_REQUIRED !== 'false';
const authDir = path.resolve('tests/.artifacts/auth');

interface WorkerAuth {
	authFile: string;
	workerIndex: number;
}

async function expectSignedIn(page: Page): Promise<void> {
	await page.getByLabel('Main navigation').waitFor({ state: 'visible', timeout: 15_000 });
}

async function authFileIsValid(browser: Browser, workerAuth: WorkerAuth): Promise<boolean> {
	if (!fs.existsSync(workerAuth.authFile)) return false;
	const context = await browser.newContext({
		baseURL,
		storageState: workerAuth.authFile
	});
	const page = await context.newPage();
	try {
		await page.goto('/', { waitUntil: 'domcontentloaded' });
		if (
			await page
				.getByLabel('Main navigation')
				.isVisible()
				.catch(() => false)
		) {
			return true;
		}
		if (
			await page
				.getByRole('heading', { name: 'Sign in', level: 1 })
				.isVisible()
				.catch(() => false)
		) {
			return false;
		}
		await expectSignedIn(page);
		return true;
	} catch {
		return false;
	} finally {
		await context.close();
	}
}

async function createAuthFile(browser: Browser, workerAuth: WorkerAuth): Promise<void> {
	fs.mkdirSync(authDir, { recursive: true });
	const context = await browser.newContext({ baseURL });
	const page = await context.newPage();
	try {
		if (authRequired) {
			const email = `e2e-ui-${E2E_RUN_STAMP}-w${workerAuth.workerIndex}@example.com`;
			await page.goto('/register', { waitUntil: 'domcontentloaded' });
			const nameInput = page.locator('#name');
			const emailInput = page.locator('#email');
			const passwordInput = page.locator('#password');
			const confirmInput = page.locator('#confirm');
			await nameInput.fill(`E2E UI Worker ${workerAuth.workerIndex}`);
			await emailInput.fill(email);
			await passwordInput.fill(E2E_PASSWORD);
			await confirmInput.fill(E2E_PASSWORD);
			await expect(nameInput).toHaveValue(`E2E UI Worker ${workerAuth.workerIndex}`);
			await expect(emailInput).toHaveValue(email);
			await expect(passwordInput).toHaveValue(E2E_PASSWORD);
			await expect(confirmInput).toHaveValue(E2E_PASSWORD);
			const createButton = page.getByRole('button', { name: 'Create account', exact: true });
			await expect(createButton).toBeEnabled({ timeout: 15_000 });
			await createButton.click();
			const continueLink = page.getByRole('link', { name: /Continue/i });
			await Promise.race([
				continueLink.waitFor({ state: 'visible', timeout: 15_000 }),
				page.getByLabel('Main navigation').waitFor({ state: 'visible', timeout: 15_000 }),
				page.getByText(/Account created\./i).waitFor({ state: 'visible', timeout: 15_000 })
			]).catch(() => undefined);
			if (await continueLink.isVisible().catch(() => false)) {
				await continueLink.click();
			} else {
				await page.goto('/', { waitUntil: 'domcontentloaded' });
			}
			await expectSignedIn(page);
		}
		const tempAuthFile = `${workerAuth.authFile}.tmp`;
		await context.storageState({ path: tempAuthFile });
		fs.renameSync(tempAuthFile, workerAuth.authFile);
	} finally {
		await context.close();
	}
}

async function ensureAuthFileReady(browser: Browser, workerAuth: WorkerAuth): Promise<void> {
	if (await authFileIsValid(browser, workerAuth)) return;
	try {
		fs.unlinkSync(workerAuth.authFile);
	} catch {
		// already removed
	}
	await createAuthFile(browser, workerAuth);
}

export const test = base.extend<{ page: Page; request: E2ERequest }, { workerAuth: WorkerAuth }>({
	workerAuth: [
		async ({ browser }, use, workerInfo) => {
			const authFile = workerAuthFile(workerInfo.workerIndex);
			const workerAuth = { authFile, workerIndex: workerInfo.workerIndex };
			await ensureAuthFileReady(browser, workerAuth);
			await use(workerAuth);
			try {
				fs.unlinkSync(authFile);
			} catch {
				// already removed
			}
		},
		{ scope: 'worker' }
	],

	page: async ({ browser, workerAuth }, use) => {
		await ensureAuthFileReady(browser, workerAuth);
		const context = await browser.newContext({
			baseURL,
			storageState: workerAuth.authFile
		});
		const page = await context.newPage();
		await use(page);
		await context.close();
	},

	request: async ({ browser, workerAuth }, use) => {
		await ensureAuthFileReady(browser, workerAuth);
		await use({
			browser,
			authFile: workerAuth.authFile,
			workerIndex: workerAuth.workerIndex,
			baseURL
		} as unknown as import('@playwright/test').APIRequestContext);
	}
});
