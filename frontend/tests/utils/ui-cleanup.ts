import type { Page } from '@playwright/test';

/**
 * UI-based cleanup helpers. Each function navigates to the relevant page,
 * finds the resource by name, and deletes it through the application's own
 * delete flow. Errors are silently caught so these are safe to call from
 * `finally` blocks even when the test has already failed.
 */

export async function deleteDatasourceViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/datasources');
		const row = page.locator(`[data-ds-row="${name}"]`);
		await row.locator('button[title="Delete"]').click({ timeout: 5_000 });
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 });
		await page.getByText(name).waitFor({ state: 'hidden', timeout: 8_000 });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteDatasourceViaUI failed for "${name}":`, e);
	}
}

export async function deleteAnalysisViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/');
		const card = page.locator(`[data-analysis-card="${name}"]`).first();
		await card.getByRole('button', { name: /Delete analysis/ }).click({ timeout: 5_000 });
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 });
		await page
			.locator(`[data-analysis-card="${name}"]`)
			.waitFor({ state: 'hidden', timeout: 8_000 });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteAnalysisViaUI failed for "${name}":`, e);
	}
}

export async function deleteUdfViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/udfs');
		const card = page.locator(`[data-udf-card="${name}"]`).first();
		await card.getByRole('button', { name: /^Delete$/i }).click({ timeout: 5_000 });
		await card.getByRole('button', { name: /Confirm/i }).click({ timeout: 5_000 });
		await page
			.locator(`[data-udf-card="${name}"]`)
			.first()
			.waitFor({ state: 'hidden', timeout: 8_000 });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteUdfViaUI failed for "${name}":`, e);
	}
}

export async function deleteScheduleViaUI(page: Page, cronOrName: string): Promise<void> {
	try {
		await page.goto('/monitoring?tab=schedules');
		const text = page.getByText(cronOrName).first();
		await text.waitFor({ state: 'visible', timeout: 8_000 });
		const row = page.locator('tr', { has: page.getByText(cronOrName) }).first();
		await row.getByLabel('Delete schedule').click({ timeout: 5_000 });
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 });
		await text.waitFor({ state: 'hidden', timeout: 8_000 });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteScheduleViaUI failed for "${cronOrName}":`, e);
	}
}

export async function deleteHealthCheckViaUI(page: Page, name: string): Promise<void> {
	try {
		await page.goto('/monitoring?tab=health');
		const text = page.getByText(name).first();
		await text.waitFor({ state: 'visible', timeout: 8_000 });
		const row = page.locator('tr', { has: page.getByText(name) }).first();
		await row.getByLabel('Delete check').click({ timeout: 5_000 });
		const dialog = page.getByRole('dialog');
		await dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 });
		await text.waitFor({ state: 'hidden', timeout: 8_000 });
	} catch (e: unknown) {
		console.warn(`[ui-cleanup] deleteHealthCheckViaUI failed for "${name}":`, e);
	}
}
