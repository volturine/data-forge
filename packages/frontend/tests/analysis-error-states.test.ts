import { test, expect } from './fixtures.js';
import { createDatasource, createAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import {
	gotoAuthedRoute,
	waitForAnalysisLoadError,
	waitForDatasourcePreviewReady
} from './utils/readiness.js';

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
			// Exercise the real datasource lifecycle before deleting the dependency.
			await page.goto(`/datasources?id=${dsId}`);
			await waitForDatasourcePreviewReady(page);
			await deleteDatasourceViaUI(page, dsName);

			// Now open the analysis that used this datasource
			await gotoAuthedRoute(page, `/analysis/${aId}`);

			// Shell should still be intact
			await expect(page.getByLabel('Main navigation')).toBeVisible({ timeout: 5_000 });

			// The analysis should show some kind of error about the missing datasource
			// or the canvas should still render but with empty/broken preview
			await expect(page.getByText(/Error|Failed|not found|datasource/i).first()).toBeVisible({
				timeout: 5_000
			});
		} finally {
			// Clean up only the exact resources created by this test. The datasource
			// deletion is part of the scenario, but may not have completed if the
			// assertion failed while the UI was still processing it.
			await deleteAnalysisViaUI(page, aName, { id: aId }).catch(() => undefined);
			await deleteDatasourceViaUI(page, dsName, { id: dsId }).catch(() => undefined);
		}
	});

	test('bad analysis ID shows error state without crashing shell', async ({ page }) => {
		const BAD_ID = '00000000-0000-0000-0000-000000000000';
		await page.goto(`/analysis/${BAD_ID}`);
		await waitForAnalysisLoadError(page);

		await expect(page.getByRole('button', { name: /Create analysis/i })).toBeVisible();

		// Shell navigation should still work
		await page.getByRole('link', { name: 'Analyses' }).click();
		await expect(page).toHaveURL('/');
		await expect(page.getByRole('heading', { name: 'Analyses', level: 1 })).toBeVisible();
	});

	test('invalid analysis ID format shows error state', async ({ page }) => {
		await page.goto('/analysis/not-a-valid-uuid');
		await waitForAnalysisLoadError(page);
	});
});
