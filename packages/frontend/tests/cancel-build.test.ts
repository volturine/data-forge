import { test, expect } from './fixtures.js';
import type { Page } from '@playwright/test';
import { createLargeDatasource, createLongRunningAnalysis } from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { waitForLayoutReady } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { uid } from './utils/uid.js';

async function startBuildFromAnalysisPage(page: Page, analysisId: string): Promise<string> {
	await gotoAnalysisEditor(page, analysisId);
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expect(buildBtn).toBeVisible({ timeout: 10_000 });
	// analysisPipeline may take a moment to populate after the lock is acquired;
	// give the button a generous timeout so we fail fast instead of consuming the
	// full 240 s test budget.
	await buildBtn.click({ timeout: 30_000 });
	const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
	await expect(openPreviewBtn).toBeVisible({ timeout: 30_000 });
	await openPreviewBtn.click({ timeout: 10_000 });
	const preview = page.locator('[data-testid="build-preview"]');
	await expect(preview).toBeVisible({ timeout: 10_000 });
	const id = preview.locator('[data-testid="build-preview-id"]');
	await expect(id).toHaveText(/\S+/, { timeout: 30_000 });
	return (await id.textContent())?.trim() ?? '';
}

async function gotoMonitoringBuilds(page: Page, analysisId?: string) {
	const params = new URLSearchParams({ tab: 'builds' });
	if (analysisId) params.set('analysis_id', analysisId);
	await page.goto(`/monitoring?${params.toString()}`);
	await waitForLayoutReady(page);
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 15_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 15_000 });
}

async function refreshBuildHistory(page: Page) {
	await page.getByRole('button', { name: /Refresh History/i }).click({ timeout: 15_000 });
}

async function openCancelDialogFromRow(page: Page, row: ReturnType<Page['locator']>) {
	const btn = row.getByLabel('Cancel build');
	await expect(btn).toBeVisible({ timeout: 10_000 });
	await expect(btn).toBeEnabled({ timeout: 10_000 });
	await btn.scrollIntoViewIfNeeded();
	await btn.click({ force: true, timeout: 10_000 });
	await expect(cancelDialog(page)).toBeVisible({ timeout: 10_000 });
}

async function openCancelDialogFromPreview(page: Page, preview: ReturnType<Page['locator']>) {
	const btn = preview.locator('[data-testid="build-cancel-button"]');
	const closeBtn = page.locator('[aria-label="Close build preview"]');
	const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
	const started = Date.now();

	while (Date.now() - started < 90_000) {
		if (await btn.isVisible().catch(() => false)) {
			await expect(btn).toBeEnabled({ timeout: 10_000 });
			await btn.scrollIntoViewIfNeeded();
			await btn.click({ force: true, timeout: 10_000 });
			await expect(cancelDialog(page)).toBeVisible({ timeout: 10_000 });
			return;
		}
		if (await closeBtn.isVisible().catch(() => false)) {
			await closeBtn.click({ timeout: 10_000 });
			await expect(preview).not.toBeVisible({ timeout: 10_000 });
		}
		await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
		await openPreviewBtn.click({ timeout: 10_000 });
		await expect(preview).toBeVisible({ timeout: 10_000 });
		await page.waitForTimeout(1_000);
	}

	throw new Error('Timed out waiting for preview cancel button to become available');
}

function cancelDialog(page: Page) {
	const title = page.getByRole('heading', { name: 'Cancel this build?' });
	return page.getByRole('dialog').filter({ has: title });
}

async function confirmCancelDialog(page: Page) {
	const dialog = cancelDialog(page);
	const confirmButton = dialog.getByRole('button', { name: 'Cancel Build', exact: true });
	await expect(dialog.getByRole('heading', { name: 'Cancel this build?' })).toBeVisible({
		timeout: 10_000
	});
	await expect(confirmButton).toBeVisible({ timeout: 10_000 });
	await expect(confirmButton).toBeEnabled({ timeout: 10_000 });
	const responsePromise = page
		.waitForResponse(
			(apiResponse) =>
				apiResponse.url().includes('/api/v1/compute/builds/') &&
				apiResponse.url().includes('/cancel') &&
				apiResponse.status() === 200,
			{ timeout: 15_000 }
		)
		.then(async (response) => (await response.json()) as { status: string })
		.catch(() => null);
	await confirmButton.click({ force: true, timeout: 10_000 });
	return responsePromise;
}

async function waitForBuildRowById(
	page: Page,
	panel: ReturnType<Page['locator']>,
	buildId: string,
	statuses: Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 30_000
) {
	const started = Date.now();
	while (Date.now() - started < timeout) {
		for (const status of statuses) {
			const row = panel.locator(`[data-build-row="${buildId}"][data-build-status="${status}"]`);
			if (await row.isVisible().catch(() => false)) return row;
		}
		await refreshBuildHistory(page);
		await page.waitForTimeout(1_000);
	}
	throw new Error(`Timed out waiting for build ${buildId} to reach ${statuses.join(' or ')}`);
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
		const dsId = await createLargeDatasource(request, dsName, 200);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId);
		try {
			await startBuildFromAnalysisPage(page, analysisId);
			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).toBeVisible({ timeout: 10_000 });
			await openCancelDialogFromPreview(page, preview);

			const dialog = cancelDialog(page);
			const payload = await confirmCancelDialog(page);
			if (payload) {
				expect(payload.status).toBe('cancelled');
			}
			await expect(dialog).not.toBeVisible({ timeout: 15_000 });
			await expect(page.locator('[data-testid="build-cancel-error"]')).not.toBeVisible();

			await expect(preview.getByText('Build cancelled')).toBeVisible({ timeout: 30_000 });
			await expect(preview.locator('[data-testid="build-cancel-button"]')).not.toBeVisible({
				timeout: 30_000
			});
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('cancel from monitoring build history row works', async ({ page, request }) => {
		test.setTimeout(240_000);
		const dsName = `e2e-cancel-history-ds-${uid()}`;
		const analysisName = `E2E Cancel History ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 200);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId);
		try {
			const buildId = await startBuildFromAnalysisPage(page, analysisId);

			// Monitoring history is explicit-refresh only, so refresh until the build row
			// appears as running before attempting the cancel action.
			await gotoMonitoringBuilds(page, analysisId);
			const panel = page.locator('#panel-builds');
			const targetRow = await waitForBuildRowById(
				page,
				panel,
				buildId,
				['queued', 'running'],
				90_000
			);
			await expect(targetRow).toBeVisible({ timeout: 10_000 });
			await expect(targetRow).toHaveAttribute('data-build-status', /^(queued|running)$/, {
				timeout: 30_000
			});
			await expect(targetRow.getByLabel('Cancel build')).toBeVisible({ timeout: 30_000 });
			await openCancelDialogFromRow(page, targetRow);

			const dialog = cancelDialog(page);
			const payload = await confirmCancelDialog(page);
			if (payload) {
				expect(payload.status).toBe('cancelled');
			}
			await expect(dialog).not.toBeVisible({ timeout: 15_000 });
			await expect(page.locator('[data-testid="build-cancel-error"]')).not.toBeVisible({
				timeout: 5_000
			});

			const cancelledRow = await waitForBuildRowById(page, panel, buildId, ['cancelled'], 30_000);
			await expect(cancelledRow).toHaveAttribute('data-build-status', 'cancelled', {
				timeout: 30_000
			});
			await expect(cancelledRow.getByText('Cancelled')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
