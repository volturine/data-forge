import type { Browser, Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';
import fs from 'node:fs';
import { workerAuthFile } from './api.js';
import { gotoAnalysesGallery, waitForDatasourceList, waitForUdfList } from './readiness.js';

const ELEMENT_VISIBLE_TIMEOUT = 10_000;
const DIALOG_HIDDEN_TIMEOUT = 10_000;
const ANALYSIS_DELETE_TIMEOUT = 45_000;

function confirmDialog(page: Page, heading: string | RegExp): Locator {
	return page
		.getByRole('dialog')
		.filter({ has: page.getByRole('heading', { name: heading }) })
		.first();
}

async function waitForHealthChecksList(page: Page, timeout: number): Promise<void> {
	const panel = page.locator('#panel-health');
	await expect(panel).toBeVisible({ timeout });
	const terminal = panel.locator(
		'[data-healthcheck-row], :text("No health checks configured."), :text("No health checks match your search."), :text("Failed to load health checks.")'
	);
	await expect
		.poll(
			async () => {
				const count = await terminal.count();
				for (let index = 0; index < count; index += 1) {
					if (
						await terminal
							.nth(index)
							.isVisible()
							.catch(() => false)
					) {
						return true;
					}
				}
				return false;
			},
			{ timeout }
		)
		.toBe(true);
}

export async function createCleanupPage(browser: Browser, workerIndex: number) {
	const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
	const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
	const authFile = workerAuthFile(workerIndex);
	const context = await browser.newContext({
		baseURL,
		...(fs.existsSync(authFile) ? { storageState: authFile } : {})
	});
	const page = await context.newPage();
	return { page, context };
}

export async function deleteDatasourceViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/datasources', { waitUntil: 'domcontentloaded' });
		await waitForDatasourceList(page, ELEMENT_VISIBLE_TIMEOUT);
		const row = page.locator(`[data-ds-row="${name}"]`);
		if (!(await row.isVisible().catch(() => false))) {
			const toggle = page.locator('button[title="Show auto-generated datasources"]');
			if (await toggle.isVisible().catch(() => false)) {
				await toggle.click();
				await waitForDatasourceList(page, ELEMENT_VISIBLE_TIMEOUT);
			}
		}
		if (!(await row.isVisible().catch(() => false))) return;
		await row.locator('button[title="Delete"]').click();
		const dialog = confirmDialog(page, 'Delete Datasource');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await expect(row).toBeHidden({ timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (error) {
		console.warn(`[ui-cleanup] deleteDatasourceViaUI failed for "${name}":`, error);
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
		const card = page.locator(`[data-analysis-card="${name}"]`);
		try {
			await card.waitFor({ state: 'visible', timeout: ELEMENT_VISIBLE_TIMEOUT });
		} catch {
			return;
		}
		await card.getByRole('button', { name: /Delete analysis/ }).click();
		const dialog = confirmDialog(page, 'Delete Analysis');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();

		const deadline = Date.now() + ANALYSIS_DELETE_TIMEOUT;
		while (Date.now() < deadline) {
			await gotoAnalysesGallery(page, ELEMENT_VISIBLE_TIMEOUT);
			const remaining = await page.locator(`[data-analysis-card="${name}"]`).count();
			if (remaining === 0) {
				return;
			}
			const deleteError = page.getByText(/^Failed to delete:/).first();
			if (await deleteError.isVisible().catch(() => false)) {
				throw new Error((await deleteError.textContent()) ?? `Failed to delete analysis ${name}`);
			}
			await page.waitForTimeout(2_000);
		}

		throw new Error(`Analysis still visible after delete flow: ${name}`);
	} catch (error) {
		console.warn(`[ui-cleanup] deleteAnalysisViaUI failed for "${name}":`, error);
	}
}

export async function deleteUdfViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/udfs', { waitUntil: 'domcontentloaded' });
		await waitForUdfList(page, ELEMENT_VISIBLE_TIMEOUT);
		const card = page.locator(`[data-udf-card="${name}"]`);
		if (!(await card.isVisible().catch(() => false))) return;
		await card.getByRole('button', { name: /^Delete$/i }).click();
		await card.getByRole('button', { name: /Confirm/i }).click();
	} catch (error) {
		console.warn(`[ui-cleanup] deleteUdfViaUI failed for "${name}":`, error);
	}
}

export async function deleteScheduleViaUI(page: Page, cronOrName: string): Promise<void> {
	try {
		await page.goto('/monitoring?tab=schedules', { waitUntil: 'domcontentloaded' });
		const row = page
			.locator('tr')
			.filter({ has: page.getByLabel('Delete schedule') })
			.filter({ hasText: cronOrName })
			.first();
		await row.waitFor({ state: 'visible', timeout: ELEMENT_VISIBLE_TIMEOUT });
		await row.getByLabel('Delete schedule').click();
		const dialog = confirmDialog(page, 'Delete Schedule');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await expect(row).toBeHidden({ timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (error) {
		console.warn(`[ui-cleanup] deleteScheduleViaUI failed for "${cronOrName}":`, error);
	}
}

export async function deleteHealthCheckViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/monitoring?tab=health', { waitUntil: 'domcontentloaded' });
		await waitForHealthChecksList(page, ELEMENT_VISIBLE_TIMEOUT);
		const row = page.locator(`[data-healthcheck-name="${name}"]`);
		await row.waitFor({ state: 'visible', timeout: ELEMENT_VISIBLE_TIMEOUT });
		await row.getByLabel('Delete check').click();
		const dialog = confirmDialog(page, 'Delete Health Check');
		await dialog.getByRole('button', { name: /^Delete$/ }).click();
		await expect(row).toBeHidden({ timeout: DIALOG_HIDDEN_TIMEOUT });
	} catch (error) {
		console.warn(`[ui-cleanup] deleteHealthCheckViaUI failed for "${name}":`, error);
	}
}
