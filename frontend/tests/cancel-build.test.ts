import { test, expect } from './fixtures.js';
import type { Page } from '@playwright/test';
import { createLargeDatasource, createLongRunningAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { waitForLayoutReady } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { uid } from './utils/uid.js';

async function startBuildFromAnalysisPage(page: Page, analysisId: string) {
	await gotoAnalysisEditor(page, analysisId);
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expect(buildBtn).toBeVisible({ timeout: 10_000 });
	await buildBtn.click();
	await expect(page.locator('[data-testid="output-build-preview-trigger"]')).toBeVisible({
		timeout: 30_000
	});
}

async function gotoMonitoringBuilds(page: Page) {
	await page.goto('/monitoring?tab=builds');
	await waitForLayoutReady(page);
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 15_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 15_000 });
}

async function openCancelDialogFromRow(page: Page, row: ReturnType<Page['locator']>) {
	const btn = row.getByLabel('Cancel build');
	await expect(btn).toBeVisible({ timeout: 10_000 });
	await btn.click();
	await expect(
		page.getByRole('dialog').getByRole('heading', { name: 'Cancel this build?' })
	).toBeVisible({ timeout: 10_000 });
}

async function openCancelDialogFromPreview(page: Page, preview: ReturnType<Page['locator']>) {
	const terminal = preview
		.getByText('Complete', { exact: true })
		.or(preview.getByText('Failed', { exact: true }))
		.or(preview.getByText('Cancelled', { exact: true }));
	const done = await terminal.isVisible().catch(() => false);
	if (done) throw new Error('Build reached terminal state before preview cancel was available');
	const btn = preview.locator('[data-testid="build-cancel-button"]');
	await expect(btn).toBeVisible({ timeout: 10_000 });
	await btn.click();
	await expect(
		page.getByRole('dialog').getByRole('heading', { name: 'Cancel this build?' })
	).toBeVisible({ timeout: 10_000 });
}

test.describe('Cancel Build – e2e', () => {
	test.describe.configure({ mode: 'serial' });

	test('cancel from build preview marks run as cancelled with details', async ({
		page,
		request
	}) => {
		test.setTimeout(240_000);
		const dsName = `e2e-cancel-preview-ds-${uid()}`;
		const analysisName = `E2E Cancel Preview ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 12_000);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId);
		try {
			await startBuildFromAnalysisPage(page, analysisId);
			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
			await openPreviewBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).toBeVisible({ timeout: 10_000 });
			await expect(preview.locator('[data-testid="build-cancel-button"]')).toBeVisible({
				timeout: 60_000
			});
			await openCancelDialogFromPreview(page, preview);

			const dialog = page.getByRole('dialog');
			await expect(dialog.getByRole('heading', { name: 'Cancel this build?' })).toBeVisible();
			await dialog.getByRole('button', { name: 'Cancel Build' }).click();

			await expect(page.locator('[data-testid="build-cancel-toast"]')).toContainText(
				'Build cancelled',
				{
					timeout: 15_000
				}
			);

			// Navigate to monitoring and find the cancelled build by analysis name
			await gotoMonitoringBuilds(page);
			const row = page.locator('tr[data-build-status="cancelled"]', {
				hasText: analysisName
			});
			await expect(row).toBeVisible({ timeout: 30_000 });

			// Expand the row and verify cancellation details
			await row.click();
			await expect(page.getByText('Cancelled At:')).toBeVisible({ timeout: 10_000 });
			await expect(page.getByText('Cancelled By:')).toBeVisible();
			await expect(page.getByText('Last Completed Step:')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('cancel from monitoring build history row works', async ({ page, request }) => {
		test.setTimeout(240_000);
		const dsName = `e2e-cancel-history-ds-${uid()}`;
		const analysisName = `E2E Cancel History ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 20_000);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId);
		try {
			await startBuildFromAnalysisPage(page, analysisId);

			// Navigate to monitoring and find the running build by analysis name
			await gotoMonitoringBuilds(page);
			const runningRow = page.locator('tr[data-build-status="running"]', {
				hasText: analysisName
			});
			await expect(runningRow).toBeVisible({ timeout: 30_000 });
			await expect(runningRow.getByLabel('Cancel build')).toBeVisible({ timeout: 30_000 });
			await openCancelDialogFromRow(page, runningRow);

			const dialog = page.getByRole('dialog');
			await expect(dialog.getByRole('heading', { name: 'Cancel this build?' })).toBeVisible();
			await dialog.getByRole('button', { name: 'Cancel Build' }).click();

			// Refresh monitoring to see the updated cancelled status
			await gotoMonitoringBuilds(page);
			const cancelledRow = page.locator('tr[data-build-status="cancelled"]', {
				hasText: analysisName
			});
			await expect(cancelledRow).toBeVisible({ timeout: 30_000 });
			await expect(cancelledRow.getByText('Cancelled')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
