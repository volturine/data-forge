import type { Browser, BrowserContext, Locator, Page } from '@playwright/test';
import { expect } from '@playwright/test';
import {
	findAnalysisIdByName,
	registeredAnalysisIds,
	registeredDatasourceIds,
	unregisterAnalysis,
	type E2EStorageState
} from './api.js';
import {
	gotoAnalysesGallery,
	gotoUdfLibrary,
	gotoMonitoringTab,
	waitForDatasourceList,
	waitForLayoutReady
} from './readiness.js';

/** Matches product `engineIdentityKey` (`scope:resource_id`). */
export type EngineUiScope = 'analysis_interactive' | 'datasource_preview' | 'build';

function engineIdentityKey(scope: EngineUiScope, resourceId: string): string {
	return `${scope}:${resourceId}`;
}

/**
 * Open the sidebar Engines popup (human path for engine lifecycle).
 * Pure UI — no direct DELETE /compute/engine/* from the test helper.
 */
export async function openEnginesPopup(page: Page): Promise<Locator> {
	const popup = page.locator('[data-engines-popup="true"]');
	if (await popup.isVisible().catch(() => false)) {
		return popup;
	}
	const trigger = page.getByRole('button', { name: 'Engine Monitor' });
	// Prefer the already-rendered shell; only re-wait for layout when the
	// monitor control is missing (cleanup after navigation / timeout paths).
	if (!(await trigger.isVisible().catch(() => false))) {
		await waitForLayoutReady(page, 5_000).catch(() => undefined);
	}
	await expect(trigger).toBeVisible({ timeout: 5_000 });
	await trigger.click();
	await expect(popup).toBeVisible({ timeout: 5_000 });
	// Stream connect shows "Loading engines..." then rows or empty state.
	await expect(popup.getByText('Loading engines...'))
		.toBeHidden({ timeout: 10_000 })
		.catch(() => undefined);
	return popup;
}

export async function closeEnginesPopup(page: Page): Promise<void> {
	const popup = page.locator('[data-engines-popup="true"]');
	if (!(await popup.isVisible().catch(() => false))) return;
	await popup
		.getByLabel('Close engines')
		.click({ timeout: 1_500 })
		.catch(() => undefined);
	await expect(popup)
		.toBeHidden({ timeout: 3_000 })
		.catch(() => undefined);
}

/**
 * Shut down one engine via the Engines popup power button.
 *
 * Warm/idle engines free immediately. If a job is still active (backend 409),
 * the product re-surfaces the row after the optimistic remove — we wait and
 * retry until the job finishes and the container is actually gone.
 */
export async function shutdownEngineViaUI(
	page: Page,
	resourceId: string,
	scope: EngineUiScope = 'analysis_interactive',
	options?: { waitForIdleMs?: number }
): Promise<void> {
	if (!resourceId || page.isClosed()) return;
	const waitForIdleMs = options?.waitForIdleMs ?? 20_000;
	const key = engineIdentityKey(scope, resourceId);
	const deadline = Date.now() + waitForIdleMs;

	while (Date.now() < deadline) {
		if (page.isClosed()) return;

		let popup: Locator;
		try {
			popup = await openEnginesPopup(page);
		} catch {
			return;
		}

		const row = popup.locator(`[data-engine-row="${key}"]`);
		const visible = await row
			.waitFor({ state: 'visible', timeout: 1_500 })
			.then(() => true)
			.catch(() => false);

		if (!visible) {
			// Stream lag: re-check once before treating as already free.
			await page.waitForTimeout(300);
			const stillMissing = !(await row.isVisible().catch(() => false));
			await closeEnginesPopup(page);
			if (stillMissing) return;
			continue;
		}

		const power = popup.locator(`[data-engine-shutdown="${key}"]`);
		if (!(await power.isEnabled().catch(() => false))) {
			await closeEnginesPopup(page);
			await page.waitForTimeout(250);
			continue;
		}

		await power.click({ timeout: 3_000 }).catch(() => undefined);
		// Product confirm: idle vs cancel-job-then-shutdown messaging.
		const confirm = page
			.getByRole('dialog')
			.filter({
				has: page.getByRole('heading', {
					name: /Shut down idle engine|Cancel job and shut down engine/i
				})
			})
			.first();
		if (await confirm.isVisible().catch(() => false)) {
			const confirmBtn = confirm.getByRole('button', {
				name: /Shut down|Cancel job & shut down/i
			});
			await confirmBtn.click({ timeout: 3_000 }).catch(() => undefined);
		}
		// Optimistic remove; settle then re-check the engines list.
		await row.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => undefined);
		await page.waitForTimeout(400);

		const reappeared = await row.isVisible().catch(() => false);
		if (!reappeared) {
			await closeEnginesPopup(page);
			// Confirm with a fresh open so we don't leave a warm container.
			try {
				const confirm = await openEnginesPopup(page);
				const stillThere = await confirm
					.locator(`[data-engine-row="${key}"]`)
					.isVisible()
					.catch(() => false);
				await closeEnginesPopup(page);
				if (!stillThere) return;
			} catch {
				return;
			}
		} else {
			await closeEnginesPopup(page);
		}

		// Job still draining — only then is the engine "busy"; wait and retry.
		await page.waitForTimeout(500);
	}

	console.warn(`[e2e] engine still present after ${waitForIdleMs}ms (likely stuck job): ${key}`);
}

export async function shutdownAnalysisEngineViaUI(
	page: Page,
	analysisId: string,
	options?: { waitForIdleMs?: number }
): Promise<void> {
	await shutdownEngineViaUI(page, analysisId, 'analysis_interactive', options);
}

export async function shutdownDatasourcePreviewEngineViaUI(
	page: Page,
	datasourceId: string,
	options?: { waitForIdleMs?: number }
): Promise<void> {
	await shutdownEngineViaUI(page, datasourceId, 'datasource_preview', options);
}

export async function shutdownBuildEngineViaUI(
	page: Page,
	buildId: string,
	options?: { waitForIdleMs?: number }
): Promise<void> {
	await shutdownEngineViaUI(page, buildId, 'build', options);
}

/**
 * Free warm Docker engines for the identities this test (or registry) owns.
 * Call after work reaches a terminal UI state so engines are idle, not busy.
 */
export async function freeWarmEnginesViaUI(
	page: Page,
	targets: {
		analysisIds?: Iterable<string>;
		datasourceIds?: Iterable<string>;
		buildIds?: Iterable<string>;
		waitForIdleMs?: number;
	} = {}
): Promise<void> {
	if (page.isClosed()) return;
	const waitForIdleMs = targets.waitForIdleMs ?? 20_000;
	const opts = { waitForIdleMs };

	for (const buildId of targets.buildIds ?? []) {
		if (!buildId) continue;
		await shutdownBuildEngineViaUI(page, buildId, opts).catch((error) => {
			console.warn(`[e2e] freeWarmEngines build ${buildId}:`, error);
		});
	}
	for (const analysisId of targets.analysisIds ?? []) {
		if (!analysisId) continue;
		await shutdownAnalysisEngineViaUI(page, analysisId, opts).catch((error) => {
			console.warn(`[e2e] freeWarmEngines analysis ${analysisId}:`, error);
		});
	}
	for (const datasourceId of targets.datasourceIds ?? []) {
		if (!datasourceId) continue;
		await shutdownDatasourcePreviewEngineViaUI(page, datasourceId, opts).catch((error) => {
			console.warn(`[e2e] freeWarmEngines datasource ${datasourceId}:`, error);
		});
	}
}

/**
 * Free warm engines for every analysis/datasource registered by this worker.
 * Prefer explicit ids when known; use this for suite-level teardown.
 */
export async function freeRegisteredWarmEnginesViaUI(page: Page): Promise<void> {
	await freeWarmEnginesViaUI(page, {
		analysisIds: registeredAnalysisIds(),
		datasourceIds: registeredDatasourceIds()
	});
}

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

export async function createCleanupPage(browser: Browser, sessionState: E2EStorageState) {
	const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
	const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
	const context = await browser.newContext({
		baseURL,
		storageState: structuredClone(sessionState)
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
	// storageState() throws if the context was already closed by test teardown.
	const storageState = await sourceContext.storageState();
	const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
	const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
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
	if (datasourceId) {
		await shutdownDatasourcePreviewEngineViaUI(page, datasourceId).catch((error) => {
			console.warn(
				`[e2e] shutdownDatasourcePreviewEngineViaUI before UI delete failed for ${datasourceId}:`,
				error
			);
		});
	}
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

/** Resolve analysis id from registry or the gallery card DOM (href / select input). */
async function resolveAnalysisIdFromCard(card: Locator, name: string): Promise<string | null> {
	const registered = findAnalysisIdByName(name);
	if (registered) return registered;
	const href = await card.getAttribute('href').catch(() => null);
	if (href) {
		const match = href.match(/\/analysis\/([^/?#]+)/);
		if (match?.[1]) return match[1];
	}
	const selectId = await card
		.locator('input[type="checkbox"][id^="analysis-"]')
		.first()
		.getAttribute('id')
		.catch(() => null);
	if (selectId) {
		const match = selectId.match(/^analysis-(.+)-select$/);
		if (match?.[1]) return match[1];
	}
	return null;
}

async function deleteAnalysisViaUIOnPage(
	page: Page,
	name: string,
	options?: { skipNavigation?: boolean }
): Promise<void> {
	if (!options?.skipNavigation) {
		await gotoAnalysesGallery(page, 1_500).catch(() => undefined);
	}
	await closeFloatingPanels(page);
	await closeFloatingPanels(page);
	const card = page.locator(`[data-analysis-card="${name}"]`);
	try {
		await card.waitFor({ state: 'visible', timeout: 1_500 });
	} catch {
		const knownId = findAnalysisIdByName(name);
		if (knownId) {
			// Card gone but engine may still be warm — free via Engines popup.
			await shutdownAnalysisEngineViaUI(page, knownId).catch(() => undefined);
			unregisterAnalysis(knownId);
		}
		return;
	}
	const analysisId = await resolveAnalysisIdFromCard(card, name);
	// Free Docker engine via visible Engines UI before deleting the analysis card.
	// Analysis DELETE also queues durable shutdown as a backstop.
	if (analysisId) {
		await shutdownAnalysisEngineViaUI(page, analysisId).catch((error) => {
			console.warn(
				`[e2e] shutdownAnalysisEngineViaUI before UI delete failed for ${analysisId}:`,
				error
			);
		});
	}
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
	if (analysisId) unregisterAnalysis(analysisId);
}

export async function deleteAnalysisViaUI(
	page: Page,
	name: string,
	options?: { skipNavigation?: boolean }
): Promise<void> {
	await runCleanupWithFallback(page, 'deleteAnalysisViaUI', name, async (cleanupPage) => {
		await deleteAnalysisViaUIOnPage(cleanupPage, name, options);
	});
}

async function deleteUdfViaUIOnPage(page: Page, name: string): Promise<void> {
	await gotoUdfLibrary(page, 5_000).catch(() => undefined);
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
	await expect(card).toBeHidden({ timeout: 5_000 });
	await gotoUdfLibrary(page, 10_000);
	await expect(page.locator(`[data-udf-card="${name}"]`)).toHaveCount(0, { timeout: 10_000 });
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
