import type { Page } from '@playwright/test';
import { test, expect } from './fixtures.js';
import { createLongRunningAnalysis, createLargeDatasource } from './utils/api.js';
import { screenshot } from './utils/visual.js';
import { waitForAppShell } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { dialogByTextbox } from './utils/locators.js';

/**
 * Smoke tests: every top-level route renders without a JS crash,
 * and primary navigation links work.
 */
test.describe('Navigation – page load smoke tests', () => {
	test('home page renders Analyses heading', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: /New Analysis/i })).toBeVisible();
		await screenshot(page, 'navigation', 'home-page');
	});

	test('datasources page renders Data Sources heading', async ({ page }) => {
		await page.goto('/datasources');
		await expect(page.getByRole('heading', { name: 'Data Sources' })).toBeVisible();
		await screenshot(page, 'navigation', 'datasources-page');
	});

	test('UDF library page renders UDF Library heading', async ({ page }) => {
		await page.goto('/udfs');
		await expect(page.getByRole('heading', { name: 'UDF Library' })).toBeVisible();
	});

	test('monitoring page renders Monitoring heading', async ({ page }) => {
		await page.goto('/monitoring');
		await expect(page.getByRole('heading', { name: 'Monitoring' })).toBeVisible({
			timeout: 10_000
		});
		await expect(page.getByRole('tab', { name: 'Builds' })).toBeVisible({ timeout: 10_000 });
		await screenshot(page, 'navigation', 'monitoring-page');
	});

	test('new analysis page renders wizard', async ({ page }) => {
		await page.goto('/analysis/new');
		await expect(page.getByRole('heading', { name: 'New Analysis' })).toBeVisible();
		await screenshot(page, 'navigation', 'new-analysis-wizard');
	});

	test('new datasource page loads', async ({ page }) => {
		await page.goto('/datasources/new');
		await expect(page).toHaveURL(/datasources\/new/);
	});

	test('new UDF page loads', async ({ page }) => {
		await page.goto('/udfs/new');
		await expect(page).toHaveURL(/udfs\/new/);
	});

	// ── header nav links ──────────────────────────────────────────────────────

	test('clicking Analyses nav link goes to /', async ({ page }) => {
		await page.goto('/datasources');
		await page.getByRole('link', { name: 'Analyses' }).click();
		await expect(page).toHaveURL('/');
	});

	test('"New Analysis" link navigates to /analysis/new', async ({ page }) => {
		await page.goto('/');
		const link = page.getByRole('link', { name: /New Analysis/i });
		await expect(link).toBeVisible();
		await link.click();
		await expect(page).toHaveURL(/analysis\/new/, { timeout: 15_000 });
	});

	test('datasources "Add" link navigates to /datasources/new', async ({ page }) => {
		await page.goto('/datasources');
		// The "Add" link is the primary CTA in the datasource left panel header
		await page.getByRole('link', { name: /^Add$/ }).click();
		await expect(page).toHaveURL(/datasources\/new/, { timeout: 10_000 });
	});

	test('UDFs "New UDF" button navigates to /udfs/new', async ({ page }) => {
		await page.goto('/udfs');
		const newUdfBtn = page.getByRole('button', { name: 'New UDF' });
		await expect(newUdfBtn).toBeVisible();
		await newUdfBtn.click();
		await expect(page).toHaveURL(/udfs\/new/, { timeout: 15_000 });
	});
});

test.describe('Navigation – profile access', () => {
	test('profile link navigates to profile page', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);
		await page.getByRole('link', { name: 'Profile' }).click();

		await page.waitForURL(/\/profile/, { timeout: 10_000 });
		await expect(page.getByRole('heading', { name: 'Profile', level: 1 })).toBeVisible();
		await expect(page.getByRole('tab', { name: 'Account' })).toHaveAttribute(
			'aria-selected',
			'true'
		);

		await screenshot(page, 'navigation', 'profile-via-sidebar');
	});
});

async function gotoMonitoringBuilds(page: Page, analysisId?: string) {
	const params = new URLSearchParams({ tab: 'builds' });
	if (analysisId) params.set('analysis_id', analysisId);
	await page.goto(`/monitoring?${params.toString()}`);
	await waitForAppShell(page);
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 15_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 15_000 });
}

async function refreshBuildHistory(page: Page) {
	await page.getByRole('button', { name: /Refresh History/i }).click({ timeout: 15_000 });
}

function cancelBuildDialog(page: Page) {
	const title = page.getByRole('heading', { name: 'Cancel this build?' });
	return page.getByRole('dialog').filter({ has: title });
}

async function confirmCancelBuild(page: Page) {
	const dialog = cancelBuildDialog(page);
	const confirmButton = dialog.getByRole('button', { name: 'Cancel Build', exact: true });
	await expect(dialog).toBeVisible({ timeout: 10_000 });
	await expect(confirmButton).toBeVisible({ timeout: 10_000 });
	await expect(confirmButton).toBeEnabled({ timeout: 10_000 });
	await confirmButton.click({ force: true, timeout: 10_000 });
	await expect(dialog).not.toBeVisible({ timeout: 15_000 });
}

async function previewBuildId(page: Page) {
	const preview = page.locator('[data-testid="build-preview"]');
	await expect(preview).toBeVisible({ timeout: 10_000 });
	const id = preview.locator('[data-testid="build-preview-id"]');
	await expect(id).toHaveText(/\S+/, { timeout: 30_000 });
	return (await id.textContent())?.trim() ?? '';
}

async function waitForBuildRowById(
	page: Page,
	panel: ReturnType<Page['locator']>,
	runId: string,
	status: 'running' | 'completed' | 'failed' | 'cancelled',
	timeout = 30_000
) {
	const row = panel.locator(`[data-build-row="${runId}"][data-build-status="${status}"]`);
	const started = Date.now();
	while (Date.now() - started < timeout) {
		if (await row.isVisible().catch(() => false)) return row;
		await refreshBuildHistory(page);
		await page.waitForTimeout(1_000);
	}
	throw new Error(`Timed out waiting for build row ${runId} to reach ${status}`);
}

test.describe('Navigation – engines live monitor', () => {
	test('engines popup lists running engines on demand', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsName = `e2e-engines-ds-${uid()}`;
		const analysisName = `E2E Engines ${uid()}`;
		const datasourceId = await createLargeDatasource(request, dsName, 200);
		const analysisId = await createLongRunningAnalysis(request, analysisName, datasourceId);

		try {
			await gotoAnalysisEditor(page, analysisId);
			await waitForAppShell(page);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();
			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 30_000 });
			await openPreviewBtn.click();
			const runId = await previewBuildId(page);
			await page.keyboard.press('Escape');
			await expect(page.locator('[data-testid="build-preview"]')).not.toBeVisible({
				timeout: 10_000
			});

			await gotoMonitoringBuilds(page, analysisId);

			const engineButton = page.getByRole('button', { name: 'Engine Monitor' });
			await expect(engineButton).toBeVisible({ timeout: 10_000 });
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
			await expect(page.getByTestId('engine-monitor-count')).toBeVisible({ timeout: 15_000 });
			await expect(enginePopup.locator('[data-engine-row]').first()).toBeVisible({
				timeout: 10_000
			});

			const panel = page.locator('#panel-builds');
			const runningRow = await waitForBuildRowById(page, panel, runId, 'running', 90_000);
			const cancelButton = runningRow.getByLabel('Cancel build');
			await expect(cancelButton).toBeVisible({ timeout: 10_000 });
			await expect(cancelButton).toBeEnabled({ timeout: 10_000 });
			await cancelButton.click({ force: true, timeout: 10_000 });
			await confirmCancelBuild(page);

			const cancelledRow = await waitForBuildRowById(page, panel, runId, 'cancelled', 30_000);
			await expect(cancelledRow.getByText('Cancelled')).toBeVisible({ timeout: 15_000 });
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
		await page.goto('/');
		await waitForAppShell(page);

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
		await page.goto('/');
		await waitForAppShell(page);

		await page.getByRole('button', { name: 'AI Assistant' }).click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		await page.keyboard.press('Escape');
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});

	test('chat panel toggle: second click closes the panel', async ({ page }) => {
		await page.goto('/');
		await waitForAppShell(page);

		const trigger = page.getByRole('button', { name: 'AI Assistant' });
		await trigger.click();
		const panel = page.locator('#chat-panel');
		await expect(panel).toBeVisible({ timeout: 5_000 });

		// Click trigger again to close
		await trigger.click();
		await expect(panel).not.toBeVisible({ timeout: 3_000 });
	});
});

test.describe('Navigation – namespace persistence', () => {
	test('selected namespace persists across page refresh', async ({ page }) => {
		test.setTimeout(30_000);
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
		await expect(sidebar.getByText(ns)).toBeVisible({ timeout: 5_000 });

		await page.reload({ waitUntil: 'networkidle' });
		await waitForAppShell(page);

		await expect(sidebar.getByText(ns)).toBeVisible({ timeout: 10_000 });
		await screenshot(page, 'navigation', 'namespace-persisted');
	});
});
