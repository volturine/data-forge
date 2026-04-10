import { test, expect } from './fixtures.js';
import { deleteAccount } from './utils/api.js';
import { createAnalysisViaUi, registerViaUi, uploadDatasourceViaUi } from './utils/user-flows.js';
import { gotoAnalysisEditor, gotoReadOnlyAnalysisEditor } from './utils/analysis.js';
import type { BrowserContext } from '@playwright/test';

async function getSessionToken(context: BrowserContext): Promise<string | undefined> {
	const state = await context.storageState();
	return state.cookies.find((cookie) => cookie.name === 'session_token')?.value;
}

test.describe('Analyses – multi-user locking', () => {
	test('second account stays read-only until the active editor leaves, then takes over', async ({
		browser
	}) => {
		test.setTimeout(180_000);

		const port = parseInt(process.env.FRONTEND_PORT || '3000', 10);
		const baseURL = `http://localhost:${port}`;
		const id = Date.now().toString(36);
		const datasourceName = `e2e-lock-ds-${id}`;
		const analysisName = `E2E Lock ${id}`;
		const userOneEmail = `e2e-lock-owner-${id}@example.com`;
		const userTwoEmail = `e2e-lock-viewer-${id}@example.com`;

		const ownerContext = await browser.newContext({ baseURL });
		const viewerContext = await browser.newContext({ baseURL });
		const ownerPage = await ownerContext.newPage();
		const viewerPage = await viewerContext.newPage();

		const ownerToken = await (async () => {
			try {
				await registerViaUi(ownerPage, userOneEmail, 'Owner User');
				return await getSessionToken(ownerContext);
			} catch (error) {
				await ownerPage.close();
				await ownerContext.close();
				throw error;
			}
		})();

		const viewerToken = await (async () => {
			try {
				await registerViaUi(viewerPage, userTwoEmail, 'Viewer User');
				return await getSessionToken(viewerContext);
			} catch (error) {
				await viewerPage.close();
				await viewerContext.close();
				if (ownerToken) {
					await deleteAccount(ownerToken).catch(() => {});
				}
				throw error;
			}
		})();

		try {
			await uploadDatasourceViaUi(ownerPage, datasourceName);
			const analysisId = await createAnalysisViaUi(ownerPage, analysisName, datasourceName);

			await gotoAnalysisEditor(ownerPage, analysisId);
			const ownerFilter = ownerPage.locator('button[data-step="filter"]').first();
			await expect(ownerFilter).toBeEnabled({ timeout: 10_000 });
			await ownerFilter.click();
			await expect(ownerPage.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 10_000
			});

			await gotoReadOnlyAnalysisEditor(viewerPage, analysisId);
			await expect(viewerPage.locator('[data-testid="lock-banner"]')).toBeVisible({
				timeout: 10_000
			});
			await expect(viewerPage.getByTestId('lock-toggle-button')).toHaveText('Locked');
			await expect(viewerPage.locator('[data-save-state="locked"]')).toBeVisible();
			await expect(viewerPage.locator('button[data-step="filter"]').first()).toBeDisabled();

			await ownerPage.getByTestId('lock-toggle-button').click();
			await expect(ownerPage.locator('[role="application"]')).toHaveAttribute(
				'data-editor-access-state',
				'released',
				{ timeout: 10_000 }
			);
			await expect(ownerPage.locator('[data-testid="lock-released-banner"]')).toBeVisible({
				timeout: 10_000
			});

			const viewerEditor = viewerPage.locator('[role="application"]');
			await expect(viewerEditor).toHaveAttribute('data-editor-access-state', 'editable', {
				timeout: 30_000
			});

			const viewerFilter = viewerPage.locator('button[data-step="filter"]').first();
			await expect(viewerFilter).toBeEnabled({ timeout: 10_000 });
			await viewerFilter.click();
			await expect(viewerPage.locator('[data-step-type="filter"]')).toHaveCount(1, {
				timeout: 10_000
			});
		} finally {
			await ownerPage.close().catch(() => {});
			await viewerPage.close().catch(() => {});
			await ownerContext.close().catch(() => {});
			await viewerContext.close().catch(() => {});
			if (viewerToken) {
				await deleteAccount(viewerToken).catch(() => {});
			}
			if (ownerToken) {
				await deleteAccount(ownerToken).catch(() => {});
			}
		}
	});
});
