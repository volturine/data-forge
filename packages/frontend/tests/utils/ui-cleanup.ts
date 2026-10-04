import type { APIRequestContext, Browser, BrowserContext, Locator, Page } from '@playwright/test';
import { expect, request as playwrightRequest } from '@playwright/test';
import {
	findAnalysisIdByName,
	findDatasourceIdsByName,
	unregisterAnalysis,
	unregisterDatasource,
	type E2EStorageState
} from './api.js';
import { installE2eContextGuards } from './page-guards.js';
import { getCleanupSessionState, rememberCleanupSessionState } from './page-session-state.js';
import { e2eBaseURL } from './base-url.js';
import { DEFAULT_NAMESPACE } from './namespace.js';
import {
	gotoAnalysesGallery,
	gotoUdfLibrary,
	gotoMonitoringTab,
	readyTimeoutMs,
	waitForDatasourceList,
	waitForLayoutReady
} from './readiness.js';

export type EngineUiScope = 'analysis_interactive' | 'datasource_preview' | 'build';

function engineApiSegment(scope: EngineUiScope): string {
	return scope === 'datasource_preview'
		? 'datasource-preview'
		: scope === 'build'
			? 'build'
			: 'analysis';
}

async function shutdownEngineForCleanup(
	page: Page,
	scope: EngineUiScope,
	resourceId: string
): Promise<void> {
	const endpoint =
		'/api/v1/compute/engine/' + engineApiSegment(scope) + '/' + encodeURIComponent(resourceId);
	const response = await page.context().request.delete(endpoint, { headers: cleanupHeaders() });
	if (!response.ok() && response.status() !== 404) {
		throw new Error(
			`Failed to shut down ${scope} engine ${resourceId}: ${(await responseFailure(response)).message}`
		);
	}
}

/**
 * Dismiss the Build Preview modal if open so shell controls (Engines) are
 * clickable. freeWarm must not fight a full-screen BaseModal backdrop.
 */
export async function closeBuildPreviewIfOpen(page: Page): Promise<void> {
	if (page.isClosed()) return;
	const preview = page.locator('[data-testid="build-preview"]');
	if (!(await preview.isVisible().catch(() => false))) return;

	const closeBtn = page.getByRole('button', { name: 'Close build preview' });
	if (await closeBtn.isVisible().catch(() => false)) {
		await closeBtn.click({ timeout: 5_000 });
	} else {
		await page.keyboard.press('Escape');
	}
	await expect(preview).toBeHidden({ timeout: 5_000 });
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
	if (!(await trigger.isVisible().catch(() => false))) {
		await waitForLayoutReady(page, 5_000).catch(() => undefined);
	}
	await expect(trigger).toBeVisible({ timeout: 5_000 });
	await trigger.click({ timeout: 5_000 });
	await expect(popup).toBeVisible({ timeout: 5_000 });
	// Settle stream: loading ends with either an empty state or a real row.
	// A timeout here must fail cleanup; treating an unsettled stream as empty
	// leaves the engine alive and contaminates the next test.
	await expect
		.poll(
			async () => {
				if (
					await popup
						.getByText('No engines running')
						.isVisible()
						.catch(() => false)
				) {
					return 'empty';
				}
				if (
					await popup
						.locator('[data-engine-row]')
						.first()
						.isVisible()
						.catch(() => false)
				) {
					return 'rows';
				}
				return 'loading';
			},
			{ timeout: 10_000, message: 'Engine monitor did not publish a settled snapshot' }
		)
		.not.toBe('loading');
	return popup;
}

export async function closeEnginesPopup(page: Page): Promise<void> {
	const popup = page.locator('[data-engines-popup="true"]');
	if (!(await popup.isVisible().catch(() => false))) return;
	await popup.getByLabel('Close engines').click({ timeout: 1_000 });
	await expect(popup).toBeHidden({ timeout: 2_000 });
}

/**
 * Shut down owned engines through exact API identities.
 *
 * This is teardown, not an Engines-popup test. The live engine stream can
 * remove a row between lookup and click, so using the authenticated API keeps
 * cleanup independent from DOM churn and cannot select another resource.
 */
export async function freeWarmEngines(
	page: Page,
	targets: {
		analysisIds?: Iterable<string>;
		datasourceIds?: Iterable<string>;
		buildIds?: Iterable<string>;
	} = {}
): Promise<void> {
	if (page.isClosed()) return;

	const resources: Array<{ scope: EngineUiScope; resourceId: string }> = [];
	for (const resourceId of targets.buildIds ?? []) {
		resources.push({ scope: 'build', resourceId });
	}
	for (const resourceId of targets.analysisIds ?? []) {
		resources.push({ scope: 'analysis_interactive', resourceId });
	}
	for (const resourceId of targets.datasourceIds ?? []) {
		resources.push({ scope: 'datasource_preview', resourceId });
	}

	for (const resource of resources) {
		if (!resource.resourceId || page.isClosed()) return;
		await shutdownEngineForCleanup(page, resource.scope, resource.resourceId);
	}
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
		await enginesPopup.getByLabel('Close engines').click({ timeout: 1_000 });
		await expect(enginesPopup).toBeHidden({ timeout: 2_000 });
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
	const context = await browser.newContext({
		baseURL: e2eBaseURL(),
		storageState: structuredClone(sessionState)
	});
	rememberCleanupSessionState(context, sessionState);
	installE2eContextGuards(context);
	const page = await context.newPage();
	return { page, context };
}

type CleanupSession = {
	context: BrowserContext;
	page: Page;
};

function cleanupHeaders(): Record<string, string> {
	return { 'X-Namespace': DEFAULT_NAMESPACE };
}

async function responseFailure(response: import('@playwright/test').APIResponse): Promise<Error> {
	const body = await response.text().catch(() => '');
	return new Error(`HTTP ${response.status()} ${body.slice(0, 300)}`);
}

async function deleteDatasourceById(page: Page, name: string, datasourceId: string): Promise<void> {
	// DELETE marks the row pending and the worker finalizes it after its
	// preview engine drains. Stop the exact owned engine first so teardown
	// cannot leave a running preview holding the datasource open.
	await shutdownEngineForCleanup(page, 'datasource_preview', datasourceId);
	const response = await page
		.context()
		.request.delete(`/api/v1/datasource/${encodeURIComponent(datasourceId)}`, {
			headers: cleanupHeaders()
		});
	if (!response.ok() && response.status() !== 404) {
		throw new Error(
			`Failed to delete datasource ${name} (${datasourceId}): ${(await responseFailure(response)).message}`
		);
	}
	unregisterDatasource(datasourceId);
}

async function deleteAnalysisByRequest(
	request: APIRequestContext,
	name: string,
	analysisId: string,
	editorClientId?: string | null
): Promise<void> {
	const headers = {
		...cleanupHeaders(),
		...(editorClientId ? { 'X-Editor-Client-Id': editorClientId } : {})
	};
	const current = await request.get(`/api/v1/analysis/${encodeURIComponent(analysisId)}`, {
		headers
	});
	if (current.status() === 404) {
		unregisterAnalysis(analysisId);
		return;
	}
	if (!current.ok()) {
		throw new Error(
			`Failed to read analysis ${name} (${analysisId}): ${(await responseFailure(current)).message}`
		);
	}
	const version = current.headers()['x-analysis-version'];
	if (!version) {
		throw new Error(`Analysis ${name} (${analysisId}) did not return X-Analysis-Version`);
	}
	// Analysis DELETE is the single owner of analysis-engine teardown. The API
	// queues the exact shutdown after the row is deleted; issuing a second
	// shutdown here races the request worker and can cancel an unrelated
	// request that reused the same engine identity.
	const response = await request.delete(`/api/v1/analysis/${encodeURIComponent(analysisId)}`, {
		headers: { ...headers, 'If-Match': version }
	});
	if (!response.ok() && response.status() !== 404) {
		throw new Error(
			`Failed to delete analysis ${name} (${analysisId}): ${(await responseFailure(response)).message}`
		);
	}
	unregisterAnalysis(analysisId);
}

async function deleteAnalysisById(page: Page, name: string, analysisId: string): Promise<void> {
	const editorClientId = await page.evaluate(() => {
		try {
			return window.sessionStorage.getItem('dataforge_editor_client_id');
		} catch {
			return null;
		}
	});
	await deleteAnalysisByRequest(page.context().request, name, analysisId, editorClientId);
}

const cleanupSessions = new WeakMap<BrowserContext, Promise<CleanupSession>>();

async function createIsolatedCleanupSession(
	sourceContext: BrowserContext
): Promise<CleanupSession> {
	const browser = sourceContext.browser();
	if (!browser) {
		throw new Error('Cleanup isolation requires an attached browser');
	}
	let storageState: E2EStorageState;
	try {
		storageState = (await sourceContext.storageState()) as E2EStorageState;
	} catch (error) {
		// Playwright closes a timed-out test's context before afterEach cleanup
		// runs. Keep immutable worker auth state outside the context so cleanup
		// can still release the test's owned resources.
		const savedState = getCleanupSessionState(sourceContext);
		if (!savedState) throw error;
		storageState = savedState;
	}
	const context = await browser.newContext({ baseURL: e2eBaseURL(), storageState });
	rememberCleanupSessionState(context, storageState);
	installE2eContextGuards(context);
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
	} catch (sourceError) {
		try {
			await withIsolatedCleanupPage(sourcePage, cleanup);
		} catch (isolatedError) {
			throw new AggregateError(
				[sourceError, isolatedError],
				`[ui-cleanup] ${label} failed for "${targetName}" on both test and isolated cleanup pages`,
				{ cause: isolatedError }
			);
		}
	}
}

async function deleteDatasourceViaUIOnPage(
	page: Page,
	name: string,
	options?: { id?: string }
): Promise<void> {
	const registeredIds = findDatasourceIdsByName(name);
	const datasourceId = options?.id ?? (registeredIds.length === 1 ? registeredIds[0] : undefined);
	if (datasourceId) {
		await deleteDatasourceById(page, name, datasourceId);
		return;
	}
	if (registeredIds.length > 1) {
		throw new Error(
			`Datasource name "${name}" has ambiguous test ownership: ${registeredIds.join(', ')}`
		);
	}
	await page.goto('/datasources', { waitUntil: 'domcontentloaded', timeout: 15_000 });
	await waitForDatasourceList(page, 5_000);
	const row = options?.id
		? page.locator(`[data-ds-id="${options.id}"]`).first()
		: page.locator(`[data-ds-row="${name}"]`).first();
	if (!(await row.isVisible().catch(() => false))) {
		const toggle = page.locator('button[title="Show auto-generated datasources"]');
		if (await toggle.isVisible().catch(() => false)) {
			await toggle.click({ timeout: 5_000 });
			await waitForDatasourceList(page, 5_000);
		}
	}
	if (!(await row.isVisible().catch(() => false))) return;
	const visibleDatasourceId = options?.id ?? (await row.getAttribute('data-ds-id'));
	if (visibleDatasourceId) {
		await freeWarmEngines(page, { datasourceIds: [visibleDatasourceId] });
	}
	const deleteResponse = visibleDatasourceId
		? page.waitForResponse(
				(response) =>
					response.request().method() === 'DELETE' &&
					response.url().includes(`/api/v1/datasource/${visibleDatasourceId}`),
				{ timeout: 5_000 }
			)
		: Promise.resolve(null);
	const deleteButton = row.locator('button[title="Delete"]');
	await expect(deleteButton).toBeEnabled({ timeout: 1_500 });
	await deleteButton.click({ timeout: 5_000 });
	const dialog = confirmDialog(page, 'Delete Datasource');
	await Promise.all([
		deleteResponse,
		dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 })
	]).then(([response]) => {
		if (response && !response.ok()) {
			throw new Error(`Failed to delete datasource ${name}: HTTP ${response.status()}`);
		}
	});
	await expect(dialog).toBeHidden({ timeout: 5_000 });
	await expect(row).toBeHidden({ timeout: 5_000 });
	if (visibleDatasourceId) unregisterDatasource(visibleDatasourceId);
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
	options?: { id?: string; skipNavigation?: boolean }
): Promise<void> {
	const ownedAnalysisId = options?.id ?? findAnalysisIdByName(name);
	if (ownedAnalysisId) {
		await deleteAnalysisById(page, name, ownedAnalysisId);
		return;
	}
	if (!options?.skipNavigation) {
		await gotoAnalysesGallery(page, readyTimeoutMs());
	}
	await closeFloatingPanels(page);
	const card = page.locator(`[data-analysis-card="${name}"]`);
	try {
		await card.waitFor({ state: 'visible', timeout: readyTimeoutMs() });
	} catch (error) {
		const knownId = findAnalysisIdByName(name);
		if (knownId) {
			throw new Error(`Analysis card "${name}" was not published for cleanup`, { cause: error });
		}
		return;
	}
	const analysisId = await resolveAnalysisIdFromCard(card, name);
	const deleteResponse = analysisId
		? page.waitForResponse(
				(response) =>
					response.request().method() === 'DELETE' &&
					response.url().includes(`/api/v1/analysis/${analysisId}`),
				{ timeout: readyTimeoutMs() }
			)
		: Promise.resolve(null);
	await card.getByRole('button', { name: /Delete analysis/ }).click({ timeout: 5_000 });
	const dialog = confirmDialog(page, 'Delete Analysis');
	await Promise.all([
		deleteResponse,
		dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 })
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
	await expect(card).toBeHidden({ timeout: readyTimeoutMs() });
	if (analysisId) unregisterAnalysis(analysisId);
}

export async function deleteAnalysisViaUI(
	page: Page,
	name: string,
	options?: { id?: string; skipNavigation?: boolean }
): Promise<void> {
	try {
		await runCleanupWithFallback(page, 'deleteAnalysisViaUI', name, async (cleanupPage) => {
			await deleteAnalysisViaUIOnPage(cleanupPage, name, options);
		});
	} catch (cleanupError) {
		const sourceContext = page.context();
		const sessionState = getCleanupSessionState(sourceContext);
		const analysisId = options?.id ?? findAnalysisIdByName(name);
		if (!sessionState || !analysisId) throw cleanupError;
		let cleanupRequest: APIRequestContext | undefined;
		try {
			cleanupRequest = await playwrightRequest.newContext({
				baseURL: e2eBaseURL(),
				storageState: structuredClone(sessionState)
			});
			await deleteAnalysisByRequest(cleanupRequest, name, analysisId);
		} catch (requestError) {
			throw new AggregateError(
				[cleanupError, requestError],
				`[ui-cleanup] ${name} cleanup failed in the UI and authenticated API fallback`,
				{ cause: requestError }
			);
		} finally {
			await cleanupRequest?.dispose().catch(() => undefined);
		}
	}
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
	await card.getByRole('button', { name: /^Delete$/i }).click({ timeout: 5_000 });
	await Promise.all([
		deleteResponse,
		card.getByRole('button', { name: /Confirm/i }).click({ timeout: 5_000 })
	]).then(([response]) => {
		if (response && !response.ok()) {
			throw new Error(`Failed to delete UDF ${name}: HTTP ${response.status()}`);
		}
	});
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

async function deleteScheduleViaUIOnPage(
	page: Page,
	cronOrName: string,
	options?: { id?: string }
): Promise<void> {
	await gotoMonitoringTab(page, 'schedules', 1_500);
	const row = options?.id
		? page.locator(`[data-schedule-row="${options.id}"]`)
		: page
				.locator('tr')
				.filter({ has: page.getByLabel('Delete schedule') })
				.filter({ hasText: cronOrName })
				.first();
	await row.waitFor({ state: 'visible', timeout: 1_500 });
	await row.getByLabel('Delete schedule').click({ timeout: 5_000 });
	const dialog = confirmDialog(page, 'Delete Schedule');
	await dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 });
	await expect(row)
		.toBeHidden({ timeout: 1_500 })
		.catch(() => undefined);
}

export async function deleteScheduleViaUI(
	page: Page,
	cronOrName: string,
	options?: { id?: string }
): Promise<void> {
	await runCleanupWithFallback(page, 'deleteScheduleViaUI', cronOrName, async (cleanupPage) => {
		await deleteScheduleViaUIOnPage(cleanupPage, cronOrName, options);
	});
}

/** Delete exactly the schedule created by the current test. */
export async function deleteScheduleById(page: Page, scheduleId: string): Promise<void> {
	const response = await page
		.context()
		.request.delete(`/api/v1/schedules/${encodeURIComponent(scheduleId)}`, {
			headers: cleanupHeaders()
		});
	if (!response.ok() && response.status() !== 404) {
		throw new Error(
			`Failed to delete schedule ${scheduleId}: ${(await responseFailure(response)).message}`
		);
	}
}

async function deleteHealthCheckViaUIOnPage(page: Page, name: string): Promise<void> {
	await gotoMonitoringTab(page, 'health', 1_500);
	await waitForHealthChecksList(page, 1_500).catch(() => undefined);
	const row = page.locator(`[data-healthcheck-name="${name}"]`);
	await row.waitFor({ state: 'visible', timeout: 1_500 });
	await row.getByLabel('Delete check').click({ timeout: 5_000 });
	const dialog = confirmDialog(page, 'Delete Health Check');
	await dialog.getByRole('button', { name: /^Delete$/ }).click({ timeout: 5_000 });
	await expect(row)
		.toBeHidden({ timeout: 1_500 })
		.catch(() => undefined);
}

export async function deleteHealthCheckViaUI(page: Page, name: string): Promise<void> {
	await runCleanupWithFallback(page, 'deleteHealthCheckViaUI', name, async (cleanupPage) => {
		await deleteHealthCheckViaUIOnPage(cleanupPage, name);
	});
}

/** Delete exactly the health check created by the current test. */
export async function deleteHealthCheckById(page: Page, healthCheckId: string): Promise<void> {
	const response = await page
		.context()
		.request.delete(`/api/v1/healthchecks/${encodeURIComponent(healthCheckId)}`, {
			headers: cleanupHeaders()
		});
	if (!response.ok() && response.status() !== 404) {
		throw new Error(
			`Failed to delete health check ${healthCheckId}: ${(await responseFailure(response)).message}`
		);
	}
}
