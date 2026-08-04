import type { Page } from '@playwright/test';
import { test, expect } from './fixtures.js';
import { createLongRunningAnalysis, createLargeDatasource } from './utils/api.js';
import { screenshot } from './utils/visual.js';
import {
	gotoAuthedRoute,
	gotoMonitoringTab,
	gotoNewAnalysis,
	gotoNewUdfPage,
	gotoUdfLibrary,
	waitForAppShell,
	waitForLayoutReady
} from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { dialogByTextbox } from './utils/locators.js';
import { waitForBuildPreview, waitForBuildPreviewId } from './utils/builds.js';

/**
 * Smoke tests: every top-level route renders without a JS crash,
 * and primary navigation links work.
 */
test.describe('Navigation – page load smoke tests', () => {
	test('home page renders Analyses heading', async ({ page }) => {
		await page.goto('/');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: /New Analysis/i })).toBeVisible();
		await screenshot(page, 'navigation', 'home-page');
	});

	test('datasources page renders Data Sources heading', async ({ page }) => {
		await page.goto('/datasources');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible();
		await screenshot(page, 'navigation', 'datasources-page');
	});

	test('UDF library page renders UDF Library heading', async ({ page }) => {
		await gotoUdfLibrary(page);
		await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible();
	});

	test('monitoring page renders Monitoring heading', async ({ page }) => {
		await page.goto('/monitoring');
		await waitForLayoutReady(page);
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible({
			timeout: 5_000
		});
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible({ timeout: 5_000 });
		await screenshot(page, 'navigation', 'monitoring-page');
	});

	test('new analysis page renders wizard', async ({ page }) => {
		await gotoNewAnalysis(page);
		await expect(page.getByRole('heading', { name: 'New Analysis' })).toBeVisible();
		await screenshot(page, 'navigation', 'new-analysis-wizard');
	});

	test('new datasource page loads', async ({ page }) => {
		await gotoAuthedRoute(page, '/datasources/new');
		await expect(page).toHaveURL(/datasources\/new/);
	});

	test('new UDF page loads', async ({ page }) => {
		await gotoNewUdfPage(page);
		await expect(page).toHaveURL(/udfs\/new/);
	});

	// ── header nav links ──────────────────────────────────────────────────────

	test('clicking Analyses nav link goes to /', async ({ page }) => {
		await page.goto('/datasources');
		await waitForLayoutReady(page);
		await page.getByRole('link', { name: 'Analyses' }).click();
		await expect(page).toHaveURL('/');
	});

	test('"New Analysis" link navigates to /analysis/new', async ({ page }) => {
		await page.goto('/');
		await waitForLayoutReady(page);
		const link = page.getByRole('link', { name: /New Analysis/i });
		await expect(link).toBeVisible();
		await link.click();
		await expect(page).toHaveURL(/analysis\/new/, { timeout: 5_000 });
	});

	test('datasources "Add" link navigates to /datasources/new', async ({ page }) => {
		await page.goto('/datasources');
		await waitForLayoutReady(page);
		// The "Add" link is the primary CTA in the datasource left panel header
		await page.getByRole('link', { name: /^Add$/ }).click();
		await expect(page).toHaveURL(/datasources\/new/, { timeout: 5_000 });
	});

	test('UDFs "New UDF" button navigates to /udfs/new', async ({ page }) => {
		await gotoUdfLibrary(page);
		const newUdfBtn = page.getByRole('button', { name: 'New UDF' });
		await expect(newUdfBtn).toBeVisible();
		await newUdfBtn.click();
		await expect(page).toHaveURL(/udfs\/new/, { timeout: 5_000 });
	});
});

test.describe('Navigation – theme toggle', () => {
	test('theme toggle switches between light and dark', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
		const initial = theme === 'dark' ? 'dark' : 'light';

		await page.getByRole('button', { name: 'Toggle theme' }).click();
		const afterToggle = await page.evaluate(() =>
			document.documentElement.getAttribute('data-theme')
		);
		expect(afterToggle).toBe(initial === 'light' ? 'dark' : 'light');

		// Toggle back
		await page.getByRole('button', { name: 'Toggle theme' }).click();
		const afterSecond = await page.evaluate(() =>
			document.documentElement.getAttribute('data-theme')
		);
		expect(afterSecond).toBe(initial);
	});
});

test.describe('Navigation – profile access', () => {
	test('profile link navigates to profile page', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);
		await page.getByRole('link', { name: 'Profile' }).click();

		await page.waitForURL(/\/profile/, { timeout: 5_000 });
		await expect(page.getByRole('heading', { name: 'Profile', level: 1 })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		await screenshot(page, 'navigation', 'profile-via-sidebar');
	});
});

async function gotoMonitoringBuilds(page: Page, analysisId?: string) {
	if (analysisId) {
		const params = new URLSearchParams({ tab: 'builds', analysis_id: analysisId });
		await page.goto(`/monitoring?${params.toString()}`);
		await waitForLayoutReady(page);
	} else {
		await gotoMonitoringTab(page, 'builds');
	}
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 5_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 5_000 });
}

async function refreshBuildHistory(page: Page) {
	const responsePromise = page
		.waitForResponse(
			(response) =>
				response.url().includes('/api/v1/compute/builds') &&
				response.request().method() === 'GET' &&
				response.ok(),
			{ timeout: 5_000 }
		)
		.catch(() => null);
	await page.getByRole('button', { name: /Refresh History/i }).click({ timeout: 5_000 });
	await responsePromise;
}

function cancelBuildDialog(page: Page) {
	const title = page.getByRole('heading', { name: 'Cancel this build?' });
	return page.getByRole('dialog').filter({ has: title });
}

async function confirmCancelBuild(page: Page) {
	const dialog = cancelBuildDialog(page);
	const confirmButton = dialog.getByRole('button', { name: 'Cancel Build', exact: true });
	await expect(dialog).toBeVisible({ timeout: 5_000 });
	await expect(confirmButton).toBeVisible({ timeout: 5_000 });
	await expect(confirmButton).toBeEnabled({ timeout: 5_000 });
	const responsePromise = page
		.waitForResponse(
			(apiResponse) =>
				apiResponse.url().includes('/api/v1/compute/builds/') &&
				apiResponse.url().includes('/cancel') &&
				apiResponse.status() === 200,
			{ timeout: 5_000 }
		)
		.then(async (response) => (await response.json()) as { status: string });
	await confirmButton.click({ force: true, timeout: 5_000 });
	const payload = await responsePromise;
	expect(payload.status).toBe('cancelled');
	await expect(dialog).not.toBeVisible({ timeout: 5_000 });
}

async function previewBuildId(page: Page) {
	await waitForBuildPreview(page);
	return waitForBuildPreviewId(page);
}

async function waitForBuildRowById(
	page: Page,
	panel: ReturnType<Page['locator']>,
	runId: string,
	statuses:
		| 'running'
		| 'completed'
		| 'failed'
		| 'cancelled'
		| 'queued'
		| Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 5_000
) {
	const acceptedStatuses = Array.isArray(statuses) ? statuses : [statuses];
	const started = Date.now();
	while (Date.now() - started < timeout) {
		const failedToLoad = panel.getByText(/Failed to load builds/i).first();
		if (await failedToLoad.isVisible().catch(() => false)) {
			throw new Error(`Build history failed while waiting for build row ${runId}`);
		}
		for (const status of acceptedStatuses) {
			const row = panel.locator(`[data-build-row="${runId}"][data-build-status="${status}"]`);
			if (await row.isVisible().catch(() => false)) return row;
		}
		if (acceptedStatuses.includes('cancelled')) {
			const completed = panel.locator(`[data-build-row="${runId}"][data-build-status="completed"]`);
			const failed = panel.locator(`[data-build-row="${runId}"][data-build-status="failed"]`);
			if (await completed.isVisible().catch(() => false)) {
				throw new Error(`Build row ${runId} completed after a confirmed cancellation`);
			}
			if (await failed.isVisible().catch(() => false)) {
				throw new Error(`Build row ${runId} failed after a confirmed cancellation`);
			}
		}
		await refreshBuildHistory(page);
		await page.waitForTimeout(250);
	}
	throw new Error(
		`Timed out waiting for build row ${runId} to reach ${acceptedStatuses.join(' or ')}`
	);
}

async function waitForBuildRowEventually(
	page: Page,
	panel: ReturnType<Page['locator']>,
	runId: string,
	statuses:
		| 'running'
		| 'completed'
		| 'failed'
		| 'cancelled'
		| 'queued'
		| Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>
) {
	let lastError: unknown;
	for (let attempt = 0; attempt < 4; attempt += 1) {
		try {
			return await waitForBuildRowById(page, panel, runId, statuses, 5_000);
		} catch (error) {
			if (error instanceof Error && error.message.includes('after a confirmed cancellation')) {
				throw error;
			}
			lastError = error;
		}
	}
	throw lastError;
}

test.describe('Navigation – engines live monitor', () => {
	test('engines popup lists running engines on demand', async ({ page, request }) => {
		const dsName = `e2e-engines-ds-${uid()}`;
		const analysisName = `E2E Engines ${uid()}`;
		const datasourceId = await createLargeDatasource(request, dsName, 200);
		const analysisId = await createLongRunningAnalysis(request, analysisName, datasourceId);

		try {
			await gotoAnalysisEditor(page, analysisId);
			await waitForAppShell(page);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 5_000 });
			await buildBtn.click();
			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 5_000 });
			await openPreviewBtn.click();
			const runId = await previewBuildId(page);
			await page.keyboard.press('Escape');
			await expect(page.locator('[data-testid="build-preview"]')).not.toBeVisible({
				timeout: 5_000
			});

			await gotoMonitoringBuilds(page, analysisId);

			const engineButton = page.getByRole('button', { name: 'Engine Monitor' });
			await expect(engineButton).toBeVisible({ timeout: 5_000 });
			const enginePopup = page.locator('[data-engines-popup="true"]');
			let open = false;
			for (let attempt = 0; attempt < 2; attempt += 1) {
				await engineButton.click();
				if (await enginePopup.isVisible().catch(() => false)) {
					open = true;
					break;
				}
				await page.waitForTimeout(250);
			}
			expect(open).toBe(true);
			await expect(page.getByTestId('engine-monitor-count')).toBeVisible({ timeout: 5_000 });
			await expect(
				enginePopup.locator(`[data-engine-row="analysis_interactive:${analysisId}"]`)
			).toBeVisible({
				timeout: 5_000
			});

			const panel = page.locator('#panel-builds');
			// Build may finish before cancel under load (especially with multi-thread
			// Polars). Engines popup already verified; only cancel while still active.
			const historyRow = await waitForBuildRowEventually(page, panel, runId, [
				'queued',
				'running',
				'completed',
				'failed',
				'cancelled'
			]);
			const status = await historyRow.getAttribute('data-build-status');
			if (status === 'queued' || status === 'running') {
				const cancelButton = historyRow.getByLabel('Cancel build');
				await expect(cancelButton).toBeVisible({ timeout: 5_000 });
				await expect(cancelButton).toBeEnabled({ timeout: 5_000 });
				await cancelButton.click({ force: true, timeout: 5_000 });
				await confirmCancelBuild(page);

				const cancelledRow = await waitForBuildRowEventually(page, panel, runId, 'cancelled');
				await expect(cancelledRow.getByText('Cancelled')).toBeVisible({ timeout: 5_000 });
			}
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Chat panel – minimal smoke tests
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Navigation – chat panel smoke', () => {
	test('chat trigger opens panel and close button dismisses it', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await expect(trigger).toBeVisible();
		await trigger.click();

		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await screenshot(page, 'navigation', 'chat-panel-open');

		// Close via the close button
		await panel.getByRole('button', { name: 'Close chat' }).click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel closes via Escape key', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		await page.getByRole('button', { name: 'AI Assistant' }).click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await page.keyboard.press('Escape');
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel toggle: second click closes the panel', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		// Click trigger again to close
		await trigger.click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel provider switch updates model selector', async ({ page }) => {
		await gotoAuthedRoute(page, '/');

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		const providerSelect = panel.locator('select[title="Chat provider"]');
		await expect(providerSelect).toBeVisible({ timeout: 3_000 });

		// Switch to Ollama — no API key required, so UI stays responsive
		await providerSelect.selectOption('ollama');
		await expect(providerSelect).toHaveValue('ollama');

		// Model button should update to Ollama default
		await expect(panel.getByRole('button', { name: 'llama3.2' })).toBeVisible({ timeout: 5_000 });
	});
});

test.describe('Navigation – namespace persistence', () => {
	test('selected namespace persists across page refresh', async ({ page }) => {
		const ns = `e2e-ns-${uid()}`;

		await page.goto('/');
		await waitForAppShell(page);

		await page.getByRole('button', { name: 'Select namespace' }).click();
		const dialog = dialogByTextbox(page, 'Search namespaces');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const search = dialog.getByRole('textbox', { name: 'Search namespaces' });
		await search.fill(ns);

		await dialog.locator(`[data-namespace-create="${ns}"]`).click();
		await expect(dialog).not.toBeVisible({ timeout: 5_000 });

		const sidebar = page.locator('aside[aria-label="Main navigation"]');
		await expect(sidebar.getByRole('button', { name: 'Select namespace' })).toContainText(ns, {
			timeout: 5_000
		});

		await page.getByRole('button', { name: 'Select namespace' }).click();
		const reopenedDialog = dialogByTextbox(page, 'Search namespaces');
		await expect(reopenedDialog).toBeVisible({ timeout: 5_000 });
		await expect(reopenedDialog.locator(`[data-namespace-option="${ns}"]`)).toBeVisible({
			timeout: 5_000
		});
		await page.keyboard.press('Escape');
		await expect(reopenedDialog).not.toBeVisible({ timeout: 5_000 });

		await page.reload({ waitUntil: 'networkidle' });
		await waitForAppShell(page);

		await expect(sidebar.getByText(ns)).toBeVisible({ timeout: 5_000 });
		await screenshot(page, 'navigation', 'namespace-persisted');
	});

	test('namespace picker search filters and selecting closes modal', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		await page.getByRole('button', { name: 'Select namespace' }).click();
		const dialog = page.locator('[role="dialog"]');
		await expect(dialog).toBeVisible({ timeout: 5_000 });

		const search = dialog.locator('#namespace-picker-search');
		await search.fill('default');
		await expect(dialog.locator('[data-namespace-option="default"]')).toBeVisible({
			timeout: 3_000
		});

		await dialog.locator('[data-namespace-option="default"]').click();
		await expect(dialog).not.toBeVisible({ timeout: 5_000 });
		await expect(page.getByRole('button', { name: 'Select namespace' })).toContainText('default');
	});
});
