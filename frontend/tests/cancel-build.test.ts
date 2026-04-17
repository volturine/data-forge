import { test, expect } from './fixtures.js';
import type { APIRequestContext, Page } from '@playwright/test';
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

async function waitForActiveBuild(
	request: APIRequestContext,
	analysisId: string,
	requireRunId = true
): Promise<{ buildId: string; runId: string | null }> {
	for (let attempt = 0; attempt < 60; attempt += 1) {
		const response = await request.get('/api/v1/compute/builds/active');
		if (response.ok()) {
			const payload = (await response.json()) as {
				builds?: Array<{
					build_id?: string;
					analysis_id?: string;
					current_engine_run_id?: string | null;
				}>;
			};
			const item = payload.builds?.find((entry) => entry.analysis_id === analysisId);
			if (item?.build_id && (!requireRunId || item.current_engine_run_id)) {
				return { buildId: item.build_id, runId: item.current_engine_run_id ?? null };
			}
		}
		await new Promise((resolve) => setTimeout(resolve, 500));
	}

	const detail = requireRunId ? 'build and engine run id' : 'active build';
	throw new Error(`Timed out waiting for ${detail} for analysis ${analysisId}`);
}

async function waitForCancelledRunId(
	request: APIRequestContext,
	analysisId: string
): Promise<string> {
	for (let attempt = 0; attempt < 60; attempt += 1) {
		const response = await request.get(
			`/api/v1/engine-runs?analysis_id=${analysisId}&status=cancelled&limit=10`
		);
		if (response.ok()) {
			const runs = (await response.json()) as Array<{ id?: string }>;
			const run = runs.find((item) => typeof item.id === 'string' && item.id.length > 0);
			if (run?.id) return run.id;
		}
		await new Promise((resolve) => setTimeout(resolve, 500));
	}

	throw new Error(`Timed out waiting for cancelled engine run for analysis ${analysisId}`);
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
		const dsId = await createLargeDatasource(request, dsName, 120_000);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId, 160);
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
			await waitForActiveBuild(request, analysisId, true);
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
			const runId = await waitForCancelledRunId(request, analysisId);

			await gotoMonitoringBuilds(page);
			const row = page.locator(`tr[data-build-row="${runId}"]`);
			await expect(row).toBeVisible({ timeout: 30_000 });
			await expect(row).toHaveAttribute('data-build-status', 'cancelled', { timeout: 30_000 });

			await row.click();
			await expect(page.locator(`tr[data-build-detail="${runId}"]`)).toBeVisible({
				timeout: 10_000
			});
			const detail = page.locator(`tr[data-build-detail="${runId}"]`);
			await expect(detail.getByText('Cancelled At:')).toBeVisible();
			await expect(detail.getByText('Cancelled By:')).toBeVisible();
			await expect(detail.getByText('Last Completed Step:')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('cancel from monitoring build history row works', async ({ page, request }) => {
		test.setTimeout(240_000);
		const dsName = `e2e-cancel-history-ds-${uid()}`;
		const analysisName = `E2E Cancel History ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 160_000);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId, 220);
		try {
			await startBuildFromAnalysisPage(page, analysisId);
			const active = await waitForActiveBuild(request, analysisId, true);

			await gotoMonitoringBuilds(page);
			const runningRow = page.locator(`tr[data-build-row="${active.runId}"]`);
			await expect(runningRow).toBeVisible({ timeout: 30_000 });
			await expect(runningRow.getByLabel('Cancel build')).toBeVisible({ timeout: 30_000 });
			await openCancelDialogFromRow(page, runningRow);

			const dialog = page.getByRole('dialog');
			await expect(dialog.getByRole('heading', { name: 'Cancel this build?' })).toBeVisible();
			await dialog.getByRole('button', { name: 'Cancel Build' }).click();
			const runId = await waitForCancelledRunId(request, analysisId);

			await gotoMonitoringBuilds(page);
			const row = page.locator(`tr[data-build-row="${runId}"][data-build-status="cancelled"]`);
			await expect(row).toHaveAttribute('data-build-status', 'cancelled', { timeout: 30_000 });
			await expect(row.getByText('Cancelled')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
