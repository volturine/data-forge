import { test, expect } from './fixtures.js';
import type { Page } from '@playwright/test';
import { createLongRunningAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI } from './utils/ui-cleanup.js';
import { readyTimeoutMs } from './utils/readiness.js';
import {
	gotoMonitoringBuilds,
	startBuildFromAnalysisPage,
	waitForBuildRowById
} from './utils/builds.js';
import { uid } from './utils/uid.js';

async function openCancelDialogFromRow(page: Page, row: ReturnType<Page['locator']>) {
	const btn = row.getByLabel('Cancel build');
	await expect(btn).toBeVisible({ timeout: 5_000 });
	await expect(btn).toBeEnabled({ timeout: 5_000 });
	await btn.scrollIntoViewIfNeeded();
	await btn.click({ force: true, timeout: 5_000 });
	await expect(cancelDialog(page)).toBeVisible({ timeout: 5_000 });
}

async function openCancelDialogFromPreview(page: Page, preview: ReturnType<Page['locator']>) {
	const btn = preview.locator('[data-testid="build-cancel-button"]');
	await expect(btn).toBeVisible({ timeout: 5_000 });
	await expect(btn).toBeEnabled({ timeout: 5_000 });
	await btn.scrollIntoViewIfNeeded();
	await btn.click({ force: true, timeout: 5_000 });
	await expect(cancelDialog(page)).toBeVisible({ timeout: 5_000 });
}

function cancelDialog(page: Page) {
	const title = page.getByRole('heading', { name: 'Cancel this build?' });
	return page.getByRole('dialog').filter({ has: title });
}

async function confirmCancelDialog(page: Page) {
	const dialog = cancelDialog(page);
	const confirmButton = dialog.getByRole('button', { name: 'Cancel Build', exact: true });
	await expect(dialog.getByRole('heading', { name: 'Cancel this build?' })).toBeVisible({
		timeout: 5_000
	});
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
		.then(async (response) => (await response.json()) as { status: string })
		.catch(() => null);
	await confirmButton.click({ force: true, timeout: 5_000 });
	return responsePromise;
}

test.describe('Cancel Build – e2e', () => {
	test.describe.configure({ mode: 'serial' });

	test('cancel from build preview marks run as cancelled with details', async ({
		page,
		request,
		sharedCancellationDatasource
	}) => {
		const analysisName = `E2E Cancel Preview ${uid()}`;
		const analysisId = await createLongRunningAnalysis(
			request,
			analysisName,
			sharedCancellationDatasource.id
		);
		try {
			await startBuildFromAnalysisPage(page, analysisId);
			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).toBeVisible({ timeout: 5_000 });
			await openCancelDialogFromPreview(page, preview);

			const dialog = cancelDialog(page);
			const payload = await confirmCancelDialog(page);
			if (payload) {
				expect(payload.status).toBe('cancelled');
			}
			await expect(dialog).not.toBeVisible({ timeout: 5_000 });
			await expect(page.locator('[data-testid="build-cancel-error"]')).not.toBeVisible();

			// Error banner text varies ("Build cancelled" vs "Cancelled by <user>");
			// status chip uses "Cancelled". Prefer the dedicated error test id.
			await expect(preview.getByTestId('build-error')).toBeVisible({ timeout: 15_000 });
			await expect(preview.getByTestId('build-error')).toHaveText(/cancelled/i, {
				timeout: 5_000
			});
			await expect(preview.locator('[data-testid="build-cancel-button"]')).toBeHidden({
				timeout: 10_000
			});
		} finally {
			await deleteAnalysisViaUI(page, analysisName).catch(() => undefined);
		}
	});

	test('cancel from monitoring build history row works', async ({
		page,
		request,
		sharedCancellationDatasource
	}) => {
		const analysisName = `E2E Cancel History ${uid()}`;
		const analysisId = await createLongRunningAnalysis(
			request,
			analysisName,
			sharedCancellationDatasource.id
		);
		let buildId: string | undefined;
		try {
			// Skip preview so we reach Monitoring while the long-running build is still active.
			buildId = await startBuildFromAnalysisPage(page, analysisId, { openPreview: false });

			// Monitoring history is explicit-refresh only, so refresh until the build row
			// appears as running before attempting the cancel action.
			await gotoMonitoringBuilds(page, analysisId);
			const panel = page.locator('#panel-builds');
			const targetRow = await waitForBuildRowById(
				page,
				panel,
				buildId,
				['queued', 'running'],
				readyTimeoutMs()
			);
			await expect(targetRow).toBeVisible({ timeout: 5_000 });
			await expect(targetRow).toHaveAttribute('data-build-status', /^(queued|running)$/, {
				timeout: 5_000
			});
			await expect(targetRow.getByLabel('Cancel build')).toBeVisible({ timeout: 5_000 });
			await openCancelDialogFromRow(page, targetRow);

			const dialog = cancelDialog(page);
			const payload = await confirmCancelDialog(page);
			if (payload) {
				expect(payload.status).toBe('cancelled');
			}
			await expect(dialog).not.toBeVisible({ timeout: 5_000 });
			await expect(page.locator('[data-testid="build-cancel-error"]')).not.toBeVisible({
				timeout: 5_000
			});

			const cancelledRow = await waitForBuildRowById(
				page,
				panel,
				buildId,
				['cancelled'],
				readyTimeoutMs()
			);
			await expect(cancelledRow).toHaveAttribute('data-build-status', 'cancelled', {
				timeout: 5_000
			});
			await expect(cancelledRow.getByText('Cancelled')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName).catch(() => undefined);
		}
	});
});
