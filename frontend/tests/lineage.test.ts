import { test, expect } from '@playwright/test';
import { createDatasource, createAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { screenshot } from './utils/visual.js';

/**
 * E2E tests for the /lineage page — data lineage graph and sidebar.
 */
test.describe('Lineage – page structure', () => {
	test('renders Data Lineage heading', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByRole('heading', { name: 'Data Lineage' })).toBeVisible();
	});

	test('shows datasource and branch selectors', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByLabel('Output datasource')).toBeVisible();
		await expect(page.getByLabel('Branch')).toBeVisible();
	});

	test('shows layout toolbar buttons', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.locator('button[title="Horizontal tree layout"]')).toBeVisible();
		await expect(page.locator('button[title="Vertical tree layout"]')).toBeVisible();
		await expect(page.locator('button[title="Grid layout"]')).toBeVisible();
	});

	test('shows zoom controls', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.locator('button[title="Zoom in"]')).toBeVisible();
		await expect(page.locator('button[title="Zoom out"]')).toBeVisible();
		await expect(page.locator('button[title="Reset view"]')).toBeVisible();
	});

	test('sidebar shows "Select a node" prompt by default', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByText('Select a node')).toBeVisible();
		await expect(page.getByText('Click a node to view details and schedules.')).toBeVisible();
		await screenshot(page, 'lineage', 'default-state');
	});

	test('branch selector is disabled when no datasource is selected', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByLabel('Branch')).toBeDisabled();
	});
});

test.describe('Lineage – layout switching', () => {
	test('clicking Vertical layout button switches to vertical mode', async ({ page }) => {
		await page.goto('/lineage');
		const verticalBtn = page.locator('button[title="Vertical tree layout"]');
		await verticalBtn.click();
		await expect(page.getByText('Vertical')).toBeVisible();
	});

	test('clicking Grid layout button switches to grid mode', async ({ page }) => {
		await page.goto('/lineage');
		const gridBtn = page.locator('button[title="Grid layout"]');
		await gridBtn.click();
		await expect(page.getByText('Grid')).toBeVisible();
	});

	test('clicking Horizontal layout button restores horizontal mode', async ({ page }) => {
		await page.goto('/lineage');
		await page.locator('button[title="Grid layout"]').click();
		await page.locator('button[title="Horizontal tree layout"]').click();
		await expect(page.getByText('Horizontal')).toBeVisible();
	});
});

test.describe('Lineage – graph interaction', () => {
	test('zoom percentage is displayed', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByText('%')).toBeVisible();
	});

	test('lineage graph loads without error state', async ({ page }) => {
		await page.goto('/lineage');
		await expect(page.getByText('Failed to load lineage.')).not.toBeVisible();
	});
});

test.describe('Lineage – with datasource data', () => {
	test('lineage graph renders nodes when datasources exist', async ({ page, request }) => {
		const dsId = await createDatasource(request, 'e2e-lineage-ds');
		await createAnalysis(request, 'E2E Lineage Analysis', dsId);
		try {
			await page.goto('/lineage');
			// The lineage graph area should not show the error state
			await expect(page.getByText('Failed to load lineage.')).not.toBeVisible();
			// The graph container should be present and not loading
			await expect(page.getByText('Loading lineage...')).not.toBeVisible({ timeout: 15_000 });
			await screenshot(page, 'lineage', 'with-data');
		} finally {
			await deleteAnalysisViaUI(page, 'E2E Lineage Analysis');
			await deleteDatasourceViaUI(page, 'e2e-lineage-ds');
		}
	});
});

// ────────────────────────────────────────────────────────────────────────────────
// Lineage – failure state regression
// ────────────────────────────────────────────────────────────────────────────────

test.describe('Lineage – error state', () => {
	test('API failure shows "Failed to load lineage." error', async ({ page }) => {
		// Intercept lineage API to return 500
		await page.route('**/api/v1/datasource/lineage*', (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' })
		);

		await page.goto('/lineage');

		// Error state should be visible
		await expect(page.locator('[data-testid="lineage-load-error"]')).toBeVisible({
			timeout: 15_000
		});
		await expect(page.getByText('Failed to load lineage.')).toBeVisible();

		// Page structure should still be intact
		await expect(page.getByRole('heading', { name: 'Data Lineage' })).toBeVisible();

		await screenshot(page, 'lineage', 'load-error-state');
	});

	test('lineage error does not crash navigation', async ({ page }) => {
		await page.route('**/api/v1/datasource/lineage*', (route) =>
			route.fulfill({ status: 500, body: 'Internal Server Error' })
		);

		await page.goto('/lineage');
		await expect(page.locator('[data-testid="lineage-load-error"]')).toBeVisible({
			timeout: 15_000
		});

		// Navigate home — shell should still work
		await page.locator('a[href="/"]').first().click();
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Analyses' })).toBeVisible();
	});
});
