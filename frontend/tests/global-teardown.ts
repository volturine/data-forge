import fs from 'node:fs';
import { chromium } from '@playwright/test';
import { AUTH_FILE, deleteAccount, login, readStoredSessionToken } from './utils/api.js';
import { waitForDatasourceList } from './utils/readiness.js';

const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
const baseURL = `http://localhost:${port}`;

const ELEMENT_TIMEOUT = 10_000;
const DIALOG_TIMEOUT = 10_000;

/**
 * Delete the E2E account, trying stored token first, then login fallback.
 * Logs the exact outcome — never silently claims success.
 */
async function deleteE2eAccount(): Promise<void> {
	const stored = readStoredSessionToken();

	if (stored) {
		const outcome = await deleteAccount(stored);
		if (outcome === 'deleted') {
			console.log('[teardown] deleted E2E account via stored token');
			return;
		}
		if (outcome === 'forbidden') {
			console.warn('[teardown] stored token references a protected account — skipping deletion');
			return;
		}
		if (outcome === 'error') {
			console.warn(
				'[teardown] unexpected error deleting with stored token — trying login fallback'
			);
		}
		// unauthenticated or error — fall through to login
	}

	const result = await login();
	if (result.status === 'invalid_credentials') {
		console.log('[teardown] E2E account does not exist (login returned 401)');
		return;
	}
	if (result.status === 'error') {
		console.warn(
			`[teardown] login fallback failed with status ${result.code} — account may still exist`
		);
		return;
	}

	const outcome = await deleteAccount(result.token);
	if (outcome === 'deleted') {
		console.log('[teardown] deleted E2E account via login fallback');
		return;
	}
	console.warn(`[teardown] delete after login returned '${outcome}' — account may still exist`);
}

export default async function globalTeardown(): Promise<void> {
	if (fs.existsSync(AUTH_FILE)) {
		const browser = await chromium.launch();
		const context = await browser.newContext({ storageState: AUTH_FILE, baseURL });
		const page = await context.newPage();

		try {
			await cleanVisibleRows(page, '/monitoring?tab=schedules', 'Delete schedule');
			await cleanVisibleRows(page, '/monitoring?tab=health', 'Delete check');
			await cleanAnalyses(page);
			await cleanDatasources(page);
			await cleanUdfs(page);
			console.log('[teardown] resource cleanup complete');
		} catch (err) {
			console.log(`[teardown] error during resource cleanup: ${err}`);
		} finally {
			await context.close();
			await browser.close();
		}
	} else {
		console.warn('[teardown] AUTH_FILE missing (setup failed early?) — skipping browser cleanup');
	}

	await deleteE2eAccount();
}

/**
 * Delete all visible rows matching the given delete button label.
 * Navigates fresh for each deletion to avoid DOM instability from TanStack Query refetches.
 */
async function cleanVisibleRows(
	page: import('@playwright/test').Page,
	url: string,
	deleteLabel: string
): Promise<void> {
	while (true) {
		try {
			await page.goto(url, { waitUntil: 'domcontentloaded' });
			const rows = page.locator('tr').filter({ has: page.getByLabel(deleteLabel) });
			try {
				await rows.first().waitFor({ state: 'visible', timeout: ELEMENT_TIMEOUT });
			} catch {
				return;
			}
			await rows.first().getByLabel(deleteLabel).click();
			const dialog = page.getByRole('dialog');
			await dialog.getByRole('button', { name: /^Delete$/ }).click();
			await dialog.waitFor({ state: 'hidden', timeout: DIALOG_TIMEOUT });
		} catch (e: unknown) {
			console.log(`[teardown] cleanVisibleRows(${deleteLabel}) stopped:`, e);
			return;
		}
	}
}

async function cleanAnalyses(page: import('@playwright/test').Page): Promise<void> {
	while (true) {
		try {
			await page.goto('/', { waitUntil: 'domcontentloaded' });
			const searchBox = page.getByRole('textbox').first();
			try {
				await searchBox.waitFor({ state: 'visible', timeout: 5_000 });
				const value = await searchBox.inputValue();
				if (value) await searchBox.fill('');
			} catch {
				// search box may not exist
			}
			const cards = page.locator('[data-analysis-card]');
			try {
				await cards.first().waitFor({ state: 'visible', timeout: ELEMENT_TIMEOUT });
			} catch {
				return;
			}
			const card = cards.first();
			const name = await card.getAttribute('data-analysis-card');
			await card.getByRole('button', { name: /Delete analysis/ }).click();
			const dialog = page.getByRole('dialog');
			await dialog.getByRole('button', { name: /^Delete$/ }).click();
			await dialog.waitFor({ state: 'hidden', timeout: DIALOG_TIMEOUT });
			console.log(`[teardown] deleted analysis "${name}"`);
		} catch (e: unknown) {
			console.log('[teardown] cleanAnalyses stopped:', e);
			return;
		}
	}
}

async function cleanDatasources(page: import('@playwright/test').Page): Promise<void> {
	while (true) {
		try {
			await page.goto('/datasources', { waitUntil: 'domcontentloaded' });
			await waitForDatasourceList(page);

			const hiddenToggle = page.locator('button[title="Show auto-generated datasources"]');
			if (await hiddenToggle.isVisible()) {
				await hiddenToggle.click();
				await waitForDatasourceList(page);
			}

			const rows = page.locator('[data-ds-row]');
			if ((await rows.count()) === 0) return;

			const row = rows.first();
			const name = await row.getAttribute('data-ds-row');
			await row.locator('button[title="Delete"]').click();
			const dialog = page.getByRole('dialog');
			await dialog.getByRole('button', { name: /^Delete$/ }).click();
			await dialog.waitFor({ state: 'hidden', timeout: DIALOG_TIMEOUT });
			console.log(`[teardown] deleted datasource "${name}"`);
		} catch (e: unknown) {
			console.log('[teardown] cleanDatasources stopped:', e);
			return;
		}
	}
}

async function cleanUdfs(page: import('@playwright/test').Page): Promise<void> {
	while (true) {
		try {
			await page.goto('/udfs', { waitUntil: 'domcontentloaded' });
			const cards = page.locator('[data-udf-card]');
			try {
				await cards.first().waitFor({ state: 'visible', timeout: ELEMENT_TIMEOUT });
			} catch {
				return;
			}
			const card = cards.first();
			const name = await card.getAttribute('data-udf-card');
			await card.getByRole('button', { name: /^Delete$/i }).click();
			await card.getByRole('button', { name: /Confirm/i }).click();
			console.log(`[teardown] deleted UDF "${name}"`);
		} catch (e: unknown) {
			console.log('[teardown] cleanUdfs stopped:', e);
			return;
		}
	}
}
