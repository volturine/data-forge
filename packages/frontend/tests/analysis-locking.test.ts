import { test, expect } from './fixtures.js';
import { createAnalysisViaUi, registerViaUi, uploadDatasourceViaUi } from './utils/user-flows.js';
import { gotoAnalysisEditor, gotoReadOnlyAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';

test.describe('Analyses – multi-user locking', () => {
	test('second account stays read-only until the active editor leaves, then takes over', async ({
		browser
	}) => {
		test.setTimeout(180_000);

		const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
		const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${port}`;
		const id = Date.now().toString(36);
		const datasourceName = `e2e-lock-ds-${id}`;
		const analysisName = `E2E Lock ${id}`;
		const userOneEmail = `e2e-lock-owner-${id}@example.com`;
		const userTwoEmail = `e2e-lock-viewer-${id}@example.com`;

		const ownerContext = await browser.newContext({ baseURL });
		const viewerContext = await browser.newContext({ baseURL });
		const ownerPage = await ownerContext.newPage();
		const viewerPage = await viewerContext.newPage();
		await registerViaUi(ownerPage, userOneEmail, 'Owner User');
		await registerViaUi(viewerPage, userTwoEmail, 'Viewer User');

		try {
			await uploadDatasourceViaUi(ownerPage, datasourceName);
			const analysisId = await createAnalysisViaUi(ownerPage, analysisName, datasourceName);

			await gotoAnalysisEditor(ownerPage, analysisId);
			const ownerFilter = ownerPage.locator('button[data-step="filter"]');
			await expect(ownerFilter).toBeEnabled({ timeout: 10_000 });
			await ownerFilter.click();
			await expect(ownerPage.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 10_000
			});

			await gotoReadOnlyAnalysisEditor(viewerPage, analysisId);
			const viewerEditor = viewerPage.locator('[role="application"]');
			await expect(viewerEditor).toHaveAttribute('data-editor-access-state', 'locked', {
				timeout: 10_000
			});
			await expect(viewerPage.getByTestId('lock-toggle-button')).toHaveAttribute(
				'aria-label',
				'Locked'
			);
			await expect(viewerPage.getByTestId('lock-toggle-button')).toBeDisabled();
			await expect(viewerPage.locator('[data-save-state="locked"]')).toBeVisible();
			await expect(viewerPage.locator('button[data-step="filter"]')).toBeDisabled();

			await ownerPage.getByTestId('lock-toggle-button').click();
			await expect(ownerPage.locator('[role="application"]')).toHaveAttribute(
				'data-editor-access-state',
				'released',
				{ timeout: 10_000 }
			);
			await expect(ownerPage.getByTestId('lock-toggle-button')).toHaveAttribute(
				'aria-label',
				'Lock',
				{ timeout: 10_000 }
			);

			await expect(viewerEditor).toHaveAttribute('data-editor-access-state', 'editable', {
				timeout: 30_000
			});

			const viewerFilter = viewerPage.locator('button[data-step="filter"]');
			await expect(viewerFilter).toBeEnabled({ timeout: 10_000 });
			await viewerFilter.click();
			await expect(viewerPage.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 10_000
			});
		} finally {
			await viewerPage.close().catch(() => {});
			await viewerContext.close().catch(() => {});
			await deleteAnalysisViaUI(ownerPage, analysisName).catch(() => {});
			await deleteDatasourceViaUI(ownerPage, datasourceName).catch(() => {});
			await ownerPage.close().catch(() => {});
			await ownerContext.close().catch(() => {});
		}
	});
});
