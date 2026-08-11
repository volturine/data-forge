import { test, expect } from './fixtures.js';
import type { Page } from '@playwright/test';
import { createLargeDatasource, createLongRunningAnalysis } from './utils/api.js';
import {
	deleteAnalysisViaUI,
	deleteDatasourceViaUI,
	shutdownBuildEngineViaUI
} from './utils/ui-cleanup.js';
import { readyTimeoutMs, waitForLayoutReady } from './utils/readiness.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { waitForBuildPreviewId } from './utils/builds.js';
import { uid } from './utils/uid.js';

async function startBuildFromAnalysisPage(
	page: Page,
	analysisId: string,
	options: { openPreview?: boolean } = {}
): Promise<string> {
	const openPreview = options.openPreview ?? true;
	await gotoAnalysisEditor(page, analysisId);
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expect(buildBtn).toBeVisible({ timeout: 5_000 });
	// Capture build id from the start response so callers can navigate away immediately
	// (e.g. monitoring cancel) without spending time opening the preview dialog.
	const started = page.waitForResponse(
		(response) => {
			if (response.request().method() !== 'POST' || !response.ok()) return false;
			// Match POST /builds start, not cancel.
			const path = new URL(response.url()).pathname;
			return path === '/api/v1/compute/builds' || path === '/api/v1/compute/builds/';
		},
		{ timeout: readyTimeoutMs() }
	);
	// analysisPipeline may take a moment to populate after the lock is acquired;
	// give the button a generous timeout so we fail fast instead of consuming the
	// full 240 s test budget.
	await buildBtn.click({ timeout: 5_000 });
	const startResponse = await started;
	const payload = (await startResponse.json()) as { build_id?: string; id?: string };
	const buildId = payload.build_id ?? payload.id;
	if (!buildId) {
		throw new Error('Build start response did not include a build id');
	}
	if (!openPreview) return buildId;

	const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
	await expect(openPreviewBtn).toBeVisible({ timeout: readyTimeoutMs() });
	await openPreviewBtn.click({ timeout: 5_000 });
	const previewId = await waitForBuildPreviewId(page);
	expect(previewId).toBe(buildId);
	return buildId;
}

async function gotoMonitoringBuilds(page: Page, analysisId?: string) {
	const params = new URLSearchParams({ tab: 'builds' });
	if (analysisId) params.set('analysis_id', analysisId);
	await page.goto(`/monitoring?${params.toString()}`);
	await waitForLayoutReady(page);
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 5_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 5_000 });
}

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

async function waitForBuildRowById(
	page: Page,
	panel: ReturnType<Page['locator']>,
	buildId: string,
	statuses: Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 5_000
) {
	const row = panel
		.locator(
			statuses
				.map((status) => `[data-build-row="${buildId}"][data-build-status="${status}"]`)
				.join(',')
		)
		.first();
	await expect(row).toBeVisible({ timeout });
	return row;
}

test.describe('Cancel Build – e2e', () => {
	test.describe.configure({ mode: 'serial' });

	test('cancel from build preview marks run as cancelled with details', async ({
		page,
		request
	}) => {
		const dsName = `e2e-cancel-preview-ds-${uid()}`;
		const analysisName = `E2E Cancel Preview ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 200);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId);
		let buildId: string | undefined;
		try {
			buildId = await startBuildFromAnalysisPage(page, analysisId);
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
			if (buildId) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, analysisName).catch(() => undefined);
			await deleteDatasourceViaUI(page, dsName).catch(() => undefined);
		}
	});

	test('cancel from monitoring build history row works', async ({ page, request }) => {
		const dsName = `e2e-cancel-history-ds-${uid()}`;
		const analysisName = `E2E Cancel History ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 200);
		const analysisId = await createLongRunningAnalysis(request, analysisName, dsId);
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
			if (buildId) {
				await shutdownBuildEngineViaUI(page, buildId).catch(() => undefined);
			}
			await deleteAnalysisViaUI(page, analysisName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
