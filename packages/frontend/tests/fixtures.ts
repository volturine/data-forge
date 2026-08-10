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
import { waitForLayoutReady } from './utils/readiness.js';

export { expect } from '@playwright/test';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
const authRequired = process.env.AUTH_REQUIRED !== 'false';

async function expectSignedIn(page: Page): Promise<void> {
	// Session bootstrap uses the same soft-reload shell gate as tests.
	const timeout = process.env.CI ? 45_000 : 15_000;
	await waitForLayoutReady(page, timeout);
}

/**
 * Register once per worker via the auth API and return Playwright storage state.
 *
 * UI registration races client hydration under Docker-engine host load and
 * fails when Playwright restarts a worker (same email → already registered).
 * API registration sets the session cookie directly; a unique stamp per call
 * keeps restarts safe. We still hard-navigate home so storage state captures a
 * settled authenticated document.
 */
async function createSessionState(browser: Browser, workerIndex: number): Promise<E2EStorageState> {
	const context = await browser.newContext({ baseURL });
	try {
		if (authRequired) {
			const email = `e2e-ui-${E2E_RUN_STAMP}-w${workerIndex}-${Date.now()}@example.com`;
			const register = await context.request.post('/api/v1/auth/register', {
				data: {
					email,
					password: E2E_PASSWORD,
					display_name: `E2E UI Worker ${workerIndex}`
				},
				timeout: 30_000
			});
			if (!register.ok()) {
				const body = await register.text().catch(() => '');
				throw new Error(
					`worker ${workerIndex}: register failed HTTP ${register.status()}: ${body}`
				);
			}
			const page = await context.newPage();
			try {
				await page.goto('/', { waitUntil: 'domcontentloaded' });
				await expectSignedIn(page);
			} finally {
				await page.close();
			}
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
