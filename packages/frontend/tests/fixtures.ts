import type { Browser, Page } from '@playwright/test';
import { expect, test as base } from '@playwright/test';
import {
	E2E_PASSWORD,
	E2E_RUN_STAMP,
	type E2ERequest,
	type E2EStorageState,
	type WorkerAuth
} from './utils/api.js';

export { expect } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
const authRequired = process.env.AUTH_REQUIRED !== 'false';

async function expectSignedIn(page: Page): Promise<void> {
	// Under CI load the shell can take longer to hydrate after navigation.
	const timeout = process.env.CI ? 15_000 : 5_000;
	await page.getByLabel('Main navigation').waitFor({ state: 'visible', timeout });
}

async function createSessionState(browser: Browser, workerIndex: number): Promise<E2EStorageState> {
	const context = await browser.newContext({ baseURL });
	const page = await context.newPage();
	try {
		if (authRequired) {
			const email = `e2e-ui-${E2E_RUN_STAMP}-w${workerIndex}@example.com`;
			await page.goto('/register', { waitUntil: 'domcontentloaded' });
			// Wait for SvelteKit hydration to complete before interacting;
			// under CI load hydration can lag behind DOMContentLoaded.
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
			// Cookie is set on the register response; hard-load home so storageState
			// captures a fully settled authenticated document (not the success panel).
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

export const test = base.extend<{ page: Page; request: E2ERequest }, { workerAuth: WorkerAuth }>({
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

	page: async ({ browser, workerAuth }, use) => {
		const context = await browser.newContext({
			baseURL,
			// Clone so Playwright cannot mutate the worker-owned session snapshot.
			storageState: structuredClone(workerAuth.sessionState)
		});
		const page = await context.newPage();
		await use(page);
		await context.close();
	},

	request: async ({ browser, workerAuth }, use) => {
		await use({
			browser,
			sessionState: workerAuth.sessionState,
			workerIndex: workerAuth.workerIndex,
			baseURL
		} as unknown as E2ERequest);
	}
});
