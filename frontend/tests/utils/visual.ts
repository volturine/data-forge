import { mkdirSync } from 'fs';
import { dirname, resolve } from 'path';
import type { Locator, Page } from '@playwright/test';

const SCREENSHOTS_DIR = resolve(import.meta.dirname, '..', 'screenshots');

function sanitize(raw: string): string {
	return raw
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '')
		.slice(0, 120);
}

/**
 * Wait for the page to reach a visually stable state before capturing.
 * Clears common loading indicators: spinners, skeleton loaders, and
 * TanStack Query loading states. Also waits for network to settle so
 * async data fetches have completed before the screenshot is taken.
 */
async function waitForStableUI(page: Page, timeout = 10_000): Promise<void> {
	const deadline = Date.now() + timeout;

	// Wait for in-flight network requests to settle first
	const networkRemaining = deadline - Date.now();
	if (networkRemaining > 0) {
		await page
			.waitForLoadState('networkidle', { timeout: Math.min(networkRemaining, 5_000) })
			.catch(() => {
				// Network may never reach idle if long-polling or websockets are active
			});
	}

	const loadingSelectors = [
		'[class*="spinner"]',
		'[data-loading="true"]',
		'text="Loading..."',
		'text="Loading lineage..."',
		'text="Loading UDF..."',
		'text="Initializing config..."',
		'text="Loading schema..."'
	];

	for (const selector of loadingSelectors) {
		const remaining = deadline - Date.now();
		if (remaining <= 0) break;
		await page
			.locator(selector)
			.waitFor({ state: 'hidden', timeout: Math.min(remaining, 500) })
			.catch(() => {
				// Indicator was never present or already hidden
			});
	}

	// Brief settle for CSS transitions / paint
	await page.waitForTimeout(200);
}

interface ScreenshotOptions {
	/** Optional locator to scope the screenshot to a specific element */
	target?: Locator;
}

/**
 * Capture a curated screenshot into `frontend/tests/screenshots/<suite>/<name>.png`.
 *
 * - `suite` groups shots by feature area (e.g. "navigation", "datasources")
 * - `name` is a short descriptor for this specific capture point
 * - Waits for network idle + loading indicators to clear before capturing
 * - Optionally scopes the screenshot to a specific element via `options.target`
 * - Directories are created automatically; names are sanitized to filesystem-safe strings
 */
export async function screenshot(
	page: Page,
	suite: string,
	name: string,
	options?: ScreenshotOptions
): Promise<void> {
	await waitForStableUI(page);
	const suitePath = suite
		.split('/')
		.map((s) => sanitize(s))
		.join('/');
	const path = `${SCREENSHOTS_DIR}/${suitePath}/${sanitize(name)}.png`;
	mkdirSync(dirname(path), { recursive: true });

	if (options?.target) {
		await options.target.screenshot({ path });
		return;
	}
	await page.screenshot({ path, fullPage: true });
}
