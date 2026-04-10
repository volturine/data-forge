import type { Browser, Page } from '@playwright/test';
import { workerAuthFile } from './api.js';
import { gotoAnalysesGallery, waitForDatasourceList, waitForUdfList } from './readiness.js';

const ELEMENT_VISIBLE_TIMEOUT = 10_000;
const DIALOG_HIDDEN_TIMEOUT = 10_000;

export async function createCleanupPage(browser: Browser, workerIndex: number) {
	const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
	const context = await browser.newContext({
		baseURL: `http://localhost:${port}`,
		storageState: workerAuthFile(workerIndex)
	});
	const page = await context.newPage();
	return { page, context };
}

export async function deleteDatasourceViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/datasources', { waitUntil: 'domcontentloaded' });
		await waitForDatasourceList(page, ELEMENT_VISIBLE_TIMEOUT);

		const row = page.locator(`[data-ds-row="${name}"]`);

		if (!(await row.isVisible())) {
			const toggle = page.locator('button[title="Show auto-generated datasources"]');
			if (await toggle.isVisible()) {
				await toggle.click();
				await waitForDatasourceList(page, ELEMENT_VISIBLE_TIMEOUT);
			}
		}

		if (!(await row.isVisible())) return;

		await row.locator('button[title="Delete"]').click();
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await dialog.waitFor({ state: 'hidden', timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteDatasourceViaUI failed for "${name}":`, e);
	}
}

export async function deleteAnalysisViaUI(
	page: Page,
	name: string,
	options?: { skipNavigation?: boolean }
): Promise<void> {
	try {
		if (!options?.skipNavigation) {
			await gotoAnalysesGallery(page, ELEMENT_VISIBLE_TIMEOUT);
		}
		const card = page.locator(`[data-analysis-card="${name}"]`).first();
		try {
			await card.waitFor({ state: 'visible', timeout: ELEMENT_VISIBLE_TIMEOUT });
		} catch {
			return;
		}
		await card.getByRole('button', { name: /Delete analysis/ }).click();
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await dialog.waitFor({ state: 'hidden', timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteAnalysisViaUI failed for "${name}":`, e);
	}
}

export async function deleteUdfViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/udfs', { waitUntil: 'domcontentloaded' });
		await waitForUdfList(page, ELEMENT_VISIBLE_TIMEOUT);
		const card = page.locator(`[data-udf-card="${name}"]`).first();
		if (!(await card.isVisible())) return;
		await card.getByRole('button', { name: /^Delete$/i }).click();
		await card.getByRole('button', { name: /Confirm/i }).click();
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteUdfViaUI failed for "${name}":`, e);
	}
}

export async function deleteScheduleViaUI(page: Page, cronOrName: string): Promise<void> {
	try {
		await page.goto('/monitoring?tab=schedules', { waitUntil: 'domcontentloaded' });
		const row = page.locator('tr', { has: page.getByText(cronOrName) }).first();
		await row.waitFor({ state: 'visible', timeout: ELEMENT_VISIBLE_TIMEOUT });
		await row.getByLabel('Delete schedule').click();
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await dialog.waitFor({ state: 'hidden', timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteScheduleViaUI failed for "${cronOrName}":`, e);
	}
}

export async function deleteHealthCheckViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/monitoring?tab=health', { waitUntil: 'domcontentloaded' });
		const row = page.locator('tr', { has: page.getByText(name) }).first();
		await row.waitFor({ state: 'visible', timeout: ELEMENT_VISIBLE_TIMEOUT });
		await row.getByLabel('Delete check').click();
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await dialog.waitFor({ state: 'hidden', timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteHealthCheckViaUI failed for "${name}":`, e);
	}
}
