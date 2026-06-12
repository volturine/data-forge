import type { Browser, BrowserContext, Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';
import fs from 'node:fs';
import { findAnalysisIdByName, workerAuthFile } from './api.js';
import {
	gotoAnalysesGallery,
	gotoMonitoringTab,
	waitForDatasourceList,
	waitForUdfList
} from './readiness.js';
import { shutdownEngineViaUi } from './user-flows.js';

function confirmDialog(page: Page, heading: string | RegExp): Locator {
	return page
		.getByRole('dialog')
		.filter({ has: page.getByRole('heading', { name: heading }) })
		.first();
}

async function closeFloatingPanels(page: Page): Promise<void> {
	const enginesPopup = page.locator('[data-engines-popup="true"]');
	if (await enginesPopup.isVisible().catch(() => false)) {
		await enginesPopup
			.getByLabel('Close engines')
			.click({ timeout: 1_000 })
			.catch(() => undefined);
	}
}

async function bestEffortShutdownAnalysisEngine(page: Page, name: string): Promise<void> {
	const analysisId = findAnalysisIdByName(name);
	if (!analysisId) return;
	try {
		await shutdownEngineViaUi(page, analysisId, { timeoutMs: 1_500 });
	} catch {
		return;
	} finally {
		await page.keyboard.press('Escape').catch(() => undefined);
	}
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

type CleanupSession = {
	context: BrowserContext;
	page: Page;
};

const cleanupSessions = new WeakMap<BrowserContext, Promise<CleanupSession>>();

async function createIsolatedCleanupSession(
	sourceContext: BrowserContext
): Promise<CleanupSession> {
	const browser = sourceContext.browser();
	if (!browser) {
		throw new Error('Cleanup isolation requires an attached browser');
	}
	const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
	const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
	const storageState = await sourceContext.storageState();
	const context = await browser.newContext({ baseURL, storageState });
	const page = await context.newPage();
	const cleanup = async () => {
		cleanupSessions.delete(sourceContext);
		await page.close().catch(() => undefined);
		await context.close().catch(() => undefined);
	};
	sourceContext.once('close', () => {
		void cleanup();
	});
	context.once('close', () => {
		cleanupSessions.delete(sourceContext);
	});
	return { context, page };
}

async function cleanupSessionFor(sourcePage: Page): Promise<CleanupSession | null> {
	const sourceContext = sourcePage.context();
	const browser = sourceContext.browser();
	if (!browser) {
		return null;
	}
	let pending = cleanupSessions.get(sourceContext);
	if (!pending) {
		pending = createIsolatedCleanupSession(sourceContext);
		cleanupSessions.set(sourceContext, pending);
	}
	return pending;
}

async function withIsolatedCleanupPage<T>(
	sourcePage: Page,
	fn: (page: Page) => Promise<T>
): Promise<T> {
	const session = await cleanupSessionFor(sourcePage);
	return fn(session?.page ?? sourcePage);
}

async function runCleanupWithFallback(
	sourcePage: Page,
	label: string,
	targetName: string,
	cleanup: (page: Page) => Promise<void>
): Promise<void> {
	try {
		await cleanup(sourcePage);
	} catch {
		try {
			await withIsolatedCleanupPage(sourcePage, cleanup);
		} catch (isolatedError) {
			console.warn(`[ui-cleanup] ${label} failed for "${targetName}":`, isolatedError);
		}
	}
}

async function deleteDatasourceViaUIOnPage(
	page: Page,
	name: string,
	options?: { id?: string }
): Promise<void> {
	await page.goto('/datasources', { waitUntil: 'domcontentloaded' });
	await waitForDatasourceList(page, 1_500).catch(() => undefined);
	const row = options?.id
		? page.locator(`[data-ds-id="${options.id}"]`).first()
		: page.locator(`[data-ds-row="${name}"]`).first();
	if (!(await row.isVisible().catch(() => false))) {
		const toggle = page.locator('button[title="Show auto-generated datasources"]');
		if (await toggle.isVisible().catch(() => false)) {
			await toggle.click();
			await waitForDatasourceList(page, 1_500).catch(() => undefined);
		}
	}
	if (!(await row.isVisible().catch(() => false))) return;
	const datasourceId = options?.id ?? (await row.getAttribute('data-ds-id'));
	const deleteResponse = datasourceId
		? page
				.waitForResponse(
					(response) =>
						response.request().method() === 'DELETE' &&
						response.url().includes(`/api/v1/datasource/${datasourceId}`),
					{ timeout: 5_000 }
				)
				.catch(() => null)
		: Promise.resolve(null);
	const deleteButton = row.locator('button[title="Delete"]');
	await expect(deleteButton).toBeEnabled({ timeout: 1_500 });
	await deleteButton.click({ timeout: 3_000 });
	const dialog = confirmDialog(page, 'Delete Datasource');
	await Promise.all([
		deleteResponse,
		dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 3_000 })
	]).then(([response]) => {
		if (response && !response.ok()) {
			throw new Error(`Failed to delete datasource ${name}: HTTP ${response.status()}`);
		}
	});
	await expect(dialog).toBeHidden({ timeout: 5_000 });
	await expect(row)
		.toBeHidden({ timeout: 5_000 })
		.catch(async () => {
			await page.goto('/datasources', { waitUntil: 'domcontentloaded' });
			await waitForDatasourceList(page, 5_000);
			await expect(row).toBeHidden({ timeout: 5_000 });
		});
}

export async function deleteDatasourceViaUI(
	page: Page,
	name: string,
	options?: { id?: string }
): Promise<void> {
	await runCleanupWithFallback(page, 'deleteDatasourceViaUI', name, async (cleanupPage) => {
		await deleteDatasourceViaUIOnPage(cleanupPage, name, options);
	});
}

async function deleteAnalysisViaUIOnPage(
	page: Page,
	name: string,
	options?: { skipNavigation?: boolean; skipEngineShutdown?: boolean }
): Promise<void> {
	if (!options?.skipNavigation) {
		await gotoAnalysesGallery(page, 1_500).catch(() => undefined);
	}
	await closeFloatingPanels(page);
	if (!options?.skipEngineShutdown) {
		await bestEffortShutdownAnalysisEngine(page, name);
	}
	await closeFloatingPanels(page);
	const card = page.locator(`[data-analysis-card="${name}"]`);
	try {
		await card.waitFor({ state: 'visible', timeout: 1_500 });
	} catch {
		return;
	}
	const analysisId = findAnalysisIdByName(name);
	const deleteResponse = analysisId
		? page
				.waitForResponse(
					(response) =>
						response.request().method() === 'DELETE' &&
						response.url().includes(`/api/v1/analysis/${analysisId}`),
					{ timeout: 5_000 }
				)
				.catch(() => null)
		: Promise.resolve(null);
	await card.getByRole('button', { name: /Delete analysis/ }).click({ timeout: 3_000 });
	const dialog = confirmDialog(page, 'Delete Analysis');
	await Promise.all([
		deleteResponse,
		dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 3_000 })
	]).then(([response]) => {
		if (response && !response.ok()) {
			throw new Error(`Failed to delete analysis ${name}: HTTP ${response.status()}`);
		}
	});
	await expect(dialog).toBeHidden({ timeout: 5_000 });
	const deleteError = page.getByText(/^Failed to delete:/).first();
	if (await deleteError.isVisible().catch(() => false)) {
		throw new Error((await deleteError.textContent()) ?? `Failed to delete analysis ${name}`);
	}
	await expect(card)
		.toBeHidden({ timeout: 5_000 })
		.catch(async () => {
			await gotoAnalysesGallery(page, 5_000);
			await expect(card).toBeHidden({ timeout: 5_000 });
		});
}

export async function deleteAnalysisViaUI(
	page: Page,
	name: string,
	options?: { skipNavigation?: boolean; skipEngineShutdown?: boolean }
): Promise<void> {
	await runCleanupWithFallback(page, 'deleteAnalysisViaUI', name, async (cleanupPage) => {
		await deleteAnalysisViaUIOnPage(cleanupPage, name, options);
	});
}

async function deleteUdfViaUIOnPage(page: Page, name: string): Promise<void> {
	await page.goto('/udfs', { waitUntil: 'domcontentloaded' });
	await waitForUdfList(page, 1_500).catch(() => undefined);
	const card = page.locator(`[data-udf-card="${name}"]`);
	if (!(await card.isVisible().catch(() => false))) return;
	const deleteResponse = page
		.waitForResponse(
			(response) =>
				response.request().method() === 'DELETE' && response.url().includes('/api/v1/udf/'),
			{ timeout: 5_000 }
		)
		.catch(() => null);
	await card.getByRole('button', { name: /^Delete$/i }).click();
	await Promise.all([deleteResponse, card.getByRole('button', { name: /Confirm/i }).click()]).then(
		([response]) => {
			if (response && !response.ok()) {
				throw new Error(`Failed to delete UDF ${name}: HTTP ${response.status()}`);
			}
		}
	);
	await expect(card)
		.toBeHidden({ timeout: 5_000 })
		.catch(async () => {
			await page.goto('/udfs', { waitUntil: 'domcontentloaded' });
			await waitForUdfList(page, 5_000);
			await expect(card).toBeHidden({ timeout: 5_000 });
		});
}

export async function deleteUdfViaUI(
	page: Page,
	name: string,
	options?: { strict?: boolean }
): Promise<void> {
	if (options?.strict) {
		await deleteUdfViaUIOnPage(page, name);
		return;
	}

	await runCleanupWithFallback(page, 'deleteUdfViaUI', name, async (cleanupPage) => {
		await deleteUdfViaUIOnPage(cleanupPage, name);
	});
}

async function deleteScheduleViaUIOnPage(page: Page, cronOrName: string): Promise<void> {
	await gotoMonitoringTab(page, 'schedules', 1_500);
	const row = page
		.locator('tr')
		.filter({ has: page.getByLabel('Delete schedule') })
		.filter({ hasText: cronOrName })
		.first();
	await row.waitFor({ state: 'visible', timeout: 1_500 });
	await row.getByLabel('Delete schedule').click();
	const dialog = confirmDialog(page, 'Delete Schedule');
	await dialog.getByRole('button', { name: /^Delete$/ }).click();
	await expect(row)
		.toBeHidden({ timeout: 1_500 })
		.catch(() => undefined);
}

export async function deleteScheduleViaUI(page: Page, cronOrName: string): Promise<void> {
	await runCleanupWithFallback(page, 'deleteScheduleViaUI', cronOrName, async (cleanupPage) => {
		await deleteScheduleViaUIOnPage(cleanupPage, cronOrName);
	});
}

async function deleteHealthCheckViaUIOnPage(page: Page, name: string): Promise<void> {
	await gotoMonitoringTab(page, 'health', 1_500);
	await waitForHealthChecksList(page, 1_500).catch(() => undefined);
	const row = page.locator(`[data-healthcheck-name="${name}"]`);
	await row.waitFor({ state: 'visible', timeout: 1_500 });
	await row.getByLabel('Delete check').click();
	const dialog = confirmDialog(page, 'Delete Health Check');
	await dialog.getByRole('button', { name: /^Delete$/ }).click();
	await expect(row)
		.toBeHidden({ timeout: 1_500 })
		.catch(() => undefined);
}

export async function deleteHealthCheckViaUI(page: Page, name: string): Promise<void> {
	await runCleanupWithFallback(page, 'deleteHealthCheckViaUI', name, async (cleanupPage) => {
		await deleteHealthCheckViaUIOnPage(cleanupPage, name);
	});
}
