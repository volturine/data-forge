import { test, expect } from './fixtures.js';
import { createAnalysisViaUi, registerViaUi, uploadDatasourceViaUi } from './utils/user-flows.js';
import { gotoAnalysisEditor, gotoReadOnlyAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { e2eBaseURL } from './utils/base-url.js';

test.describe('Analyses – multi-user locking', () => {
	test('second account stays read-only until the active editor leaves, then takes over', async ({
		browser
	}) => {
		const baseURL = e2eBaseURL();
		const id = Date.now().toString(36);
		const datasourceName = `e2e-lock-ds-${id}`;
		const analysisName = `E2E Lock ${id}`;
		const userOneEmail = `e2e-lock-owner-${id}@example.com`;
		const userTwoEmail = `e2e-lock-viewer-${id}@example.com`;

		const ownerContext = await browser.newContext({ baseURL });
		const viewerContext = await browser.newContext({ baseURL });
		const ownerPage = await ownerContext.newPage();
		const viewerPage = await viewerContext.newPage();
		let datasourceId: string | undefined;
		let analysisId: string | undefined;
		await registerViaUi(ownerPage, userOneEmail, 'Owner User');
		await registerViaUi(viewerPage, userTwoEmail, 'Viewer User');

		try {
			datasourceId = (await uploadDatasourceViaUi(ownerPage, datasourceName)).id;
			analysisId = await createAnalysisViaUi(ownerPage, analysisName, datasourceName);

			await gotoAnalysisEditor(ownerPage, analysisId);
			const ownerFilter = ownerPage.locator('button[data-step="filter"]');
			await expect(ownerFilter).toBeEnabled({ timeout: 5_000 });
			await ownerFilter.click();
			await expect(ownerPage.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 5_000
			});

			await gotoReadOnlyAnalysisEditor(viewerPage, analysisId);
			const viewerEditor = viewerPage.locator('[role="application"]');
			await expect(viewerEditor).toHaveAttribute('data-editor-access-state', 'locked', {
				timeout: 5_000
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
				{ timeout: 5_000 }
			);
			await expect(ownerPage.getByTestId('lock-toggle-button')).toHaveAttribute(
				'aria-label',
				'Lock',
				{ timeout: 5_000 }
			);

			await expect(viewerEditor).toHaveAttribute('data-editor-access-state', 'editable', {
				timeout: 5_000
			});

			const viewerFilter = viewerPage.locator('button[data-step="filter"]');
			await expect(viewerFilter).toBeEnabled({ timeout: 5_000 });
			await viewerFilter.click();
			await expect(viewerPage.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 5_000
			});
		} finally {
			await viewerPage.close().catch(() => {});
			await viewerContext.close().catch(() => {});
			// This test creates unique resources. Delete those exact identities so
			// another shard's same-named data or a stale gallery row can never be
			// selected during teardown.
			if (analysisId) {
				await deleteAnalysisViaUI(ownerPage, analysisName, { id: analysisId }).catch(() => {});
			}
			if (datasourceId) {
				await deleteDatasourceViaUI(ownerPage, datasourceName, { id: datasourceId }).catch(
					() => {}
				);
			}
			await ownerPage.close().catch(() => {});
			await ownerContext.close().catch(() => {});
		}
	});
});
