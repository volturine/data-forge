import { test, expect } from './fixtures.js';
import { deleteAccount, shutdownEngineByToken } from './utils/api.js';
import { createAnalysisViaUi, registerViaUi, uploadDatasourceViaUi } from './utils/user-flows.js';
import { gotoAnalysisEditor, gotoReadOnlyAnalysisEditor } from './utils/analysis.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
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

		let analysisId: string | undefined;
		try {
			await uploadDatasourceViaUi(ownerPage, datasourceName);
			analysisId = await createAnalysisViaUi(ownerPage, analysisName, datasourceName);

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
				{
					timeout: 10_000
				}
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
			if (ownerToken && analysisId) {
				await shutdownEngineByToken(ownerToken, analysisId).catch(() => {});
			}

			await ownerPage.close().catch(() => {});
			await viewerPage.close().catch(() => {});
			await ownerContext.close().catch(() => {});
			await viewerContext.close().catch(() => {});

			if (ownerToken) {
				const cleanupCtx = await browser.newContext({
					baseURL,
					storageState: {
						cookies: [
							{
								name: 'session_token',
								value: ownerToken,
								domain: 'localhost',
								path: '/',
								expires: -1,
								httpOnly: true,
								secure: false,
								sameSite: 'Lax' as const
							}
						],
						origins: []
					}
				});
				const cleanupPage = await cleanupCtx.newPage();
				await deleteAnalysisViaUI(cleanupPage, analysisName).catch(() => {});
				await deleteDatasourceViaUI(cleanupPage, datasourceName).catch(() => {});
				await cleanupPage.close().catch(() => {});
				await cleanupCtx.close().catch(() => {});
			}

			if (viewerToken) {
				await deleteAccount(viewerToken).catch(() => {});
			}
			if (ownerToken) {
				await deleteAccount(ownerToken).catch(() => {});
			}
		}
	});
});
