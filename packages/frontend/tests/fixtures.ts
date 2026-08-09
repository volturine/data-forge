import type { Browser, BrowserContext, Page } from '@playwright/test';
import { expect, test as base } from '@playwright/test';
import {
	E2E_PASSWORD,
	E2E_RUN_STAMP,
	type E2ERequest,
	type E2EStorageState,
	type WorkerAuth
} from './utils/api.js';
import { createRequestTrace } from './utils/request-trace.js';

export { expect } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
const authRequired = process.env.AUTH_REQUIRED !== 'false';

async function expectSignedIn(page: Page): Promise<void> {
	const timeout = process.env.CI ? 15_000 : 5_000;
	await page.getByLabel('Main navigation').waitFor({ state: 'visible', timeout });
}

/**
 * Register once per worker and return Playwright storage state.
 * Session cookies are set by the register API; we hard-navigate home so the
 * captured state is a settled authenticated document.
 */
async function createSessionState(browser: Browser, workerIndex: number): Promise<E2EStorageState> {
	const context = await browser.newContext({ baseURL });
	const page = await context.newPage();
	try {
		if (authRequired) {
			const email = `e2e-ui-${E2E_RUN_STAMP}-w${workerIndex}@example.com`;
			await page.goto('/register', { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');
			await page.locator('[data-auth-form-ready="true"]').waitFor({ timeout: 10_000 });
			const nameInput = page.locator('#name');
			const emailInput = page.locator('#email');
			const passwordInput = page.locator('#password');
			const confirmInput = page.locator('#confirm');
			await nameInput.fill(`E2E UI Worker ${workerIndex}`);
			await emailInput.fill(email);
			await passwordInput.fill(E2E_PASSWORD);
			await confirmInput.fill(E2E_PASSWORD);
			await expect(nameInput).toHaveValue(`E2E UI Worker ${workerIndex}`);
			await expect(emailInput).toHaveValue(email);
			await expect(passwordInput).toHaveValue(E2E_PASSWORD);
			await expect(confirmInput).toHaveValue(E2E_PASSWORD);
			const createButton = page.getByRole('button', { name: 'Create account', exact: true });
			await expect(createButton).toBeEnabled({ timeout: 5_000 });
			await createButton.click();
			await expect(page.getByText(/Account created\./i)).toBeVisible({ timeout: 15_000 });
			await page.goto('/', { waitUntil: 'networkidle' });
			await expectSignedIn(page);
		}
		const sessionState = (await context.storageState()) as E2EStorageState;
		if (authRequired && !sessionState.cookies.some((cookie) => cookie.name === 'session_token')) {
			throw new Error(`worker ${workerIndex}: session_token cookie missing after registration`);
		}
		return sessionState;
	} finally {
		await context.close();
	}
}

type WorkerFixtures = {
	workerAuth: WorkerAuth;
	/** One BrowserContext per worker for setup helpers (upload, import, shutdown). */
	helperContext: BrowserContext;
};

type TestFixtures = {
	page: Page;
	request: E2ERequest;
	requestTrace: import('./utils/request-trace.js').RequestTrace | null;
};

export const test = base.extend<TestFixtures, WorkerFixtures>({
	workerAuth: [
		async ({ browser }, use, workerInfo) => {
			const sessionState = await createSessionState(browser, workerInfo.workerIndex);
			await use({
				workerIndex: workerInfo.workerIndex,
				sessionState
			});
		},
		{ scope: 'worker' }
	],

	helperContext: [
		async ({ browser, workerAuth }, use) => {
			// Reuse one context for all withAuthedPage work on this worker.
			// Creating a fresh context per helper call thrashs Chromium under
			// parallel workers and starves runtime-worker heartbeats → 503s.
			const context = await browser.newContext({
				baseURL,
				storageState: structuredClone(workerAuth.sessionState)
			});
			await use(context);
			await context.close();
		},
		{ scope: 'worker' }
	],

	page: async ({ browser, workerAuth }, use) => {
		const context = await browser.newContext({
			baseURL,
			storageState: structuredClone(workerAuth.sessionState)
		});
		const page = await context.newPage();
		await use(page);
		await context.close();
	},

	request: async ({ browser, workerAuth, helperContext }, use) => {
		await use({
			browser,
			sessionState: workerAuth.sessionState,
			helperContext,
			workerIndex: workerAuth.workerIndex,
			baseURL
		} as unknown as E2ERequest);
	},

	requestTrace: [
		async ({ page }, use, testInfo) => {
			const trace = createRequestTrace(page, testInfo.workerIndex, testInfo.title, testInfo.testId);
			await use(trace);
			trace?.attach();
		},
		{ scope: 'test', auto: true }
	]
});
