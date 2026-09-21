import { mkdir, readFile, rename, rmdir, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import type { Browser, BrowserContext, Page } from '@playwright/test';
import { expect, test as base } from '@playwright/test';
import {
	E2E_PASSWORD,
	E2E_GLOBAL_RUN_STAMP,
	E2E_RUN_STAMP,
	createDatasource,
	createDatasourceWithDates,
	createLargeDatasource,
	type E2ERequest,
	type E2EStorageState,
	type WorkerAuth
} from './utils/api.js';
import { installE2eContextGuards } from './utils/page-guards.js';
import { e2eBaseURL } from './utils/base-url.js';
import { createRequestTrace } from './utils/request-trace.js';
import { waitForLayoutReady } from './utils/readiness.js';

export { expect } from '@playwright/test';

const baseURL = e2eBaseURL();
const authRequired = process.env.AUTH_REQUIRED !== 'false';
const SHARED_DATASOURCE_DESCRIPTION =
	'Primary customer dataset for retention analysis and reporting.';

async function expectSignedIn(page: Page): Promise<void> {
	const timeout = process.env.CI ? 45_000 : 15_000;
	await waitForLayoutReady(page, timeout);
}

/**
 * Register once per worker through the real register UI (same path a person
 * uses) and return Playwright storage state. Unique emails keep worker
 * restarts from colliding with an already-registered account.
 */
async function createSessionState(browser: Browser, workerIndex: number): Promise<E2EStorageState> {
	const context = await browser.newContext({ baseURL });
	installE2eContextGuards(context);
	const page = await context.newPage();
	try {
		if (authRequired) {
			// Unique per session so a Playwright worker restart does not collide.
			const email = `e2e-ui-${E2E_RUN_STAMP}-w${workerIndex}-${Date.now()}@example.com`;
			await page.goto('/register', { waitUntil: 'domcontentloaded', timeout: 15_000 });
			// The auth route is prerendered. Visible inputs can exist before Svelte
			// hydration has attached bind:value, which would leave valid input in the
			// DOM but keep the derived submit state stale under parallel startup.
			await expect(page.locator('form[data-auth-form-ready="true"]')).toBeVisible({
				timeout: 15_000
			});
			// Ready the way a person is: form fields are visible and interactive.
			const nameInput = page.locator('#name');
			await expect(nameInput).toBeVisible({ timeout: 15_000 });
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
			await createButton.click({ timeout: 15_000 });
			await expect(page.getByText(/Account created\./i)).toBeVisible({ timeout: 15_000 });
			await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 15_000 });
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
	/** One immutable baseline dataset per Playwright shard. */
	sharedDatasource: SharedDatasource;
	/** A second immutable baseline dataset per Playwright shard. */
	sharedAuxDatasource: SharedDatasource;
	/** One shard-scoped dataset with the date column required by timeseries tests. */
	sharedDateDatasource: SharedDatasource;
	/** Alias of the base dataset for chart tests. */
	sharedChartDatasource: SharedDatasource;
	/** One shard-scoped large dataset reused by sampling, cancellation, pagination, and builds. */
	sharedBulkDatasource: SharedDatasource;
	/** Alias of the shared bulk dataset for sampling tests. */
	sharedSampleDatasource: SharedDatasource;
	/** Alias of the shared bulk dataset for cancellation tests. */
	sharedCancellationDatasource: SharedDatasource;
	/** Alias of the shared bulk dataset for preview pagination tests. */
	sharedPaginationDatasource: SharedDatasource;
	/** Alias of the shared bulk dataset for long-running build tests. */
	sharedLargeBuildDatasource: SharedDatasource;
};

export type SharedDatasource = {
	id: string;
	name: string;
};

type SharedDatasourceUse = (datasource: SharedDatasource) => Promise<void>;

type TestFixtures = {
	page: Page;
	request: E2ERequest;
	requestTrace: import('./utils/request-trace.js').RequestTrace | null;
};

function workerRequest(
	browser: Browser,
	workerAuth: WorkerAuth,
	helperContext: BrowserContext
): E2ERequest {
	return {
		browser,
		sessionState: workerAuth.sessionState,
		helperContext,
		workerIndex: workerAuth.workerIndex,
		baseURL
	} as E2ERequest;
}

async function provideSharedDatasource(
	request: E2ERequest,
	name: string,
	create: (request: E2ERequest, name: string) => Promise<string>,
	use: SharedDatasourceUse
): Promise<void> {
	// Playwright workers are separate Node processes. A worker-scoped fixture
	// therefore created one identical dataset per browser worker, which flooded
	// the one runtime with duplicate ingestion and preview identities.
	// The global stamp is shared by every shard container because the repository
	// is bind-mounted into all runners. A small file rendezvous therefore
	// creates each immutable fixture once for the whole run, while every browser
	// context still owns its own mutable page/session state. These fixtures are
	// read-only by contract; tests that delete or mutate a datasource create a
	// uniquely named datasource for themselves.
	const fixtureRoot = path.join(
		process.cwd(),
		'tests',
		'.artifacts',
		'shared-fixtures',
		E2E_GLOBAL_RUN_STAMP.replace(/[^a-zA-Z0-9_-]/g, '_')
	);
	const markerPath = path.join(fixtureRoot, `${name.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`);
	const lockPath = `${markerPath}.lockdir`;
	const readOnly = process.env.E2E_SHARED_FIXTURES_READ_ONLY === '1';
	await mkdir(fixtureRoot, { recursive: true });

	const readMarker = async (): Promise<SharedDatasource | null> => {
		try {
			const marker = JSON.parse(await readFile(markerPath, 'utf8')) as Partial<SharedDatasource>;
			if (typeof marker.id === 'string' && typeof marker.name === 'string') {
				return { id: marker.id, name: marker.name };
			}
		} catch (error) {
			const code = (error as NodeJS.ErrnoException).code;
			if (code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
		}
		return null;
	};

	const deadline = Date.now() + 180_000;
	while (Date.now() < deadline) {
		const existing = await readMarker();
		if (existing) {
			await use(existing);
			return;
		}
		if (readOnly) {
			await new Promise((resolve) => setTimeout(resolve, 100));
			continue;
		}

		try {
			// mkdir is atomic across the bind mount used by the shard container.
			// Keeping the lock as a directory avoids an open-file lifetime race
			// between Node worker processes.
			await mkdir(lockPath);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
			await new Promise((resolve) => setTimeout(resolve, 100));
			continue;
		}

		let shared: SharedDatasource;
		try {
			const createdByAnotherWorker = await readMarker();
			shared = createdByAnotherWorker ?? { id: await create(request, name), name };
			if (!createdByAnotherWorker) {
				// Publish with rename so no worker can observe half-written JSON.
				const temporaryMarkerPath = `${markerPath}.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2)}.tmp`;
				try {
					await writeFile(temporaryMarkerPath, `${JSON.stringify(shared)}\n`, 'utf8');
					await rename(temporaryMarkerPath, markerPath);
				} finally {
					await unlink(temporaryMarkerPath).catch(() => undefined);
				}
			}
		} finally {
			await rmdir(lockPath).catch(() => undefined);
		}
		await use(shared);
		return;
	}
	throw new Error(`Timed out waiting for shared E2E dataset ${name} to be created`);
}

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
			installE2eContextGuards(context);
			await use(context);
			await context.close();
		},
		{ scope: 'worker' }
	],

	sharedDatasource: [
		async ({ browser, workerAuth, helperContext }, use) => {
			const request = workerRequest(browser, workerAuth, helperContext);
			const name = `e2e-shared-dataset-${E2E_GLOBAL_RUN_STAMP}`;
			await provideSharedDatasource(
				request,
				name,
				(requestForDatasource, datasourceName) =>
					createDatasource(
						requestForDatasource,
						datasourceName,
						undefined,
						SHARED_DATASOURCE_DESCRIPTION
					),
				use
			);
		},
		{ scope: 'worker' }
	],

	sharedAuxDatasource: [
		async ({ browser, workerAuth, helperContext }, use) => {
			const request = workerRequest(browser, workerAuth, helperContext);
			const name = `e2e-shared-aux-dataset-${E2E_GLOBAL_RUN_STAMP}`;
			await provideSharedDatasource(request, name, createDatasource, use);
		},
		{ scope: 'worker' }
	],

	sharedDateDatasource: [
		async ({ browser, workerAuth, helperContext }, use) => {
			const request = workerRequest(browser, workerAuth, helperContext);
			const name = `e2e-shared-date-dataset-${E2E_GLOBAL_RUN_STAMP}`;
			await provideSharedDatasource(request, name, createDatasourceWithDates, use);
		},
		{ scope: 'worker' }
	],

	sharedChartDatasource: [
		async ({ sharedDatasource }, use) => use(sharedDatasource),
		{ scope: 'worker' }
	],

	sharedBulkDatasource: [
		async ({ browser, workerAuth, helperContext }, use) => {
			const request = workerRequest(browser, workerAuth, helperContext);
			const name = `e2e-shared-bulk-dataset-${E2E_GLOBAL_RUN_STAMP}`;
			await provideSharedDatasource(
				request,
				name,
				(requestForDatasource, datasourceName) =>
					createLargeDatasource(requestForDatasource, datasourceName, 2000),
				use
			);
		},
		{ scope: 'worker' }
	],

	sharedSampleDatasource: [
		async ({ sharedBulkDatasource }, use) => use(sharedBulkDatasource),
		{ scope: 'worker' }
	],

	sharedCancellationDatasource: [
		async ({ sharedBulkDatasource }, use) => use(sharedBulkDatasource),
		{ scope: 'worker' }
	],

	sharedPaginationDatasource: [
		async ({ sharedBulkDatasource }, use) => use(sharedBulkDatasource),
		{ scope: 'worker' }
	],

	sharedLargeBuildDatasource: [
		async ({ sharedBulkDatasource }, use) => use(sharedBulkDatasource),
		{ scope: 'worker' }
	],

	page: async ({ browser, workerAuth }, use) => {
		// A test owns its browser state. Reusing a worker context lets IndexedDB,
		// cached query data, and namespace selections leak from one test into the
		// next even when the server-side resources are unique.
		const context = await browser.newContext({
			baseURL,
			storageState: structuredClone(workerAuth.sessionState)
		});
		installE2eContextGuards(context);
		const page = await context.newPage();
		try {
			await use(page);
		} finally {
			await context.close();
		}
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
