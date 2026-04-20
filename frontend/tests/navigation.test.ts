import { test, expect } from './fixtures.js';
import {
	createDatasource,
	createAnalysis,
	shutdownEngine as shutdownEngineViaApi
} from './utils/api.js';
import { screenshot } from './utils/visual.js';
import { waitForAppShell } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';

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
		const newUdfBtn = page.getByRole('button', { name: /New UDF/i });
		await expect(newUdfBtn).toBeVisible();
		await newUdfBtn.click();
		await expect(page).toHaveURL(/udfs\/new/);
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

test.describe('Navigation – engines live monitor', () => {
	test('sidebar badge and engines popup update in real time', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsName = `e2e-engines-ds-${uid()}`;
		const analysisName = `E2E Engines ${uid()}`;
		const datasourceId = await createDatasource(request, dsName);
		const analysisId = await createAnalysis(request, analysisName, datasourceId);

		try {
			// Start a build from the analysis editor — this spawns a compute engine
			await gotoAnalysisEditor(page, analysisId);
			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();
			await expect(page.locator('[data-testid="output-build-preview-trigger"]')).toBeVisible({
				timeout: 30_000
			});

			// Engine badge should appear in the sidebar
			const engineBadge = page.getByTestId('engine-monitor-count');
			await expect(engineBadge).toBeVisible({ timeout: 15_000 });

			// Open engine popup and verify the engine is listed
			const engineButton = page.getByRole('button', { name: 'Engine Monitor' });
			await engineButton.click();
			const dialog = page.getByRole('dialog', { name: 'Engines' });
			await expect(dialog).toBeVisible({ timeout: 5_000 });
			await expect(dialog.getByText(analysisId, { exact: true })).toBeVisible({
				timeout: 10_000
			});

			// Shut down engine and verify it disappears (no UI path for shutdown — Tier 3 cleanup)
			await shutdownEngineViaApi(request, analysisId);
			await expect(dialog.getByText(analysisId, { exact: true })).not.toBeVisible({
				timeout: 10_000
			});
		} finally {
			try {
				await shutdownEngineViaApi(request, analysisId);
			} catch {
				// Engine may already be stopped or build may have finished — ignore cleanup errors
			}
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
		const dialog = page.getByRole('dialog');
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
