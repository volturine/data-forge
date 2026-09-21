import { expect, test } from './fixtures.js';
import { e2eBaseURL } from './utils/base-url.js';
import {
	gotoDatasourcesPage,
	readyTimeoutMs,
	waitForDatasourcePreviewReady
} from './utils/readiness.js';

const rawBrowserCount = process.env.E2E_CONCURRENCY_BROWSERS?.trim() ?? '';
const browserCount = rawBrowserCount ? Number.parseInt(rawBrowserCount, 10) : 0;

if (rawBrowserCount && (!Number.isInteger(browserCount) || browserCount < 1)) {
	throw new Error(`E2E_CONCURRENCY_BROWSERS must be a positive integer, got "${rawBrowserCount}"`);
}

test.describe('Concurrent authenticated browser sessions', () => {
	test.describe.configure({ mode: 'parallel' });

	if (browserCount === 0) {
		test('opt-in concurrency probe', () => {
			test.skip(true, 'Set E2E_CONCURRENCY_BROWSERS to enable the concurrency probe');
		});
	} else {
		test(`opens ${browserCount} isolated browser contexts and previews one shared dataset concurrently`, async ({
			browser,
			workerAuth,
			sharedDatasource
		}) => {
			const baseURL = e2eBaseURL();
			const storageState = workerAuth.sessionState;
			const contexts = await Promise.all(
				Array.from({ length: browserCount }, () =>
					browser.newContext({ baseURL, storageState: structuredClone(storageState) })
				)
			);
			try {
				const pages = await Promise.all(contexts.map((context) => context.newPage()));
				try {
					await Promise.all(
						pages.map(async (page) => {
							await gotoDatasourcesPage(page, readyTimeoutMs());
							await page.locator(`[data-ds-row="${sharedDatasource.name}"]`).click();
							await waitForDatasourcePreviewReady(page, 120_000);
							await expect(
								page.locator('[data-preview-ready="true"]').getByText('Alice', { exact: true })
							).toBeVisible();
							await expect(page.locator('[data-column-id="id"]')).toBeVisible();
						})
					);
				} finally {
					await Promise.all(pages.map((page) => page.close()));
				}
			} finally {
				await Promise.all(contexts.map((context) => context.close()));
			}
		});
	}
});
