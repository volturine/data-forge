import { test, expect } from './fixtures.js';
import { createDatasource, createAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';

/**
 * E2E tests for analysis editor error states.
 */
test.describe('Analysis – error states', () => {
	test('analysis with deleted datasource shows error without crashing shell', async ({
		page,
		request
	}) => {
		const dsName = `e2e-err-ds-${uid()}`;
		const aName = `E2E Error ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			// Delete the datasource via UI first
			await deleteDatasourceViaUI(page, dsName);

			// Now open the analysis that used this datasource
			await page.goto(`/analysis/${aId}`);
			await expect(page.locator('[role="application"]')).toBeVisible({ timeout: 5_000 });

			// Shell should still be intact
			await expect(page.getByLabel('Main navigation')).toBeVisible({ timeout: 5_000 });

			// The analysis should show some kind of error about the missing datasource
			// or the canvas should still render but with empty/broken preview
			await expect(page.getByText(/Error|Failed|not found|datasource/i).first()).toBeVisible({
				timeout: 5_000
			});
		} finally {
			// Clean up analysis if it still exists
			await deleteAnalysisViaUI(page, aName);
		}
	});

	test('bad analysis ID shows error state without crashing shell', async ({ page }) => {
		const BAD_ID = '00000000-0000-0000-0000-000000000000';
		await page.goto(`/analysis/${BAD_ID}`);

		await expect(page.locator('[data-testid="analysis-load-error"]')).toBeVisible({
			timeout: 5_000
		});
		await expect(page.getByText('Error loading analysis')).toBeVisible();

		await expect(page.getByRole('button', { name: /Create analysis/i })).toBeVisible();

		// Shell navigation should still work
		await page.getByRole('link', { name: 'Analyses' }).click();
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
	});

	test('invalid analysis ID format shows error state', async ({ page }) => {
		await page.goto('/analysis/not-a-valid-uuid');

		await expect(page.locator('[data-testid="analysis-load-error"]')).toBeVisible({
			timeout: 5_000
		});
		await expect(page.getByText('Error loading analysis')).toBeVisible();
	});
});
