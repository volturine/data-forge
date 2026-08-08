import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { createDatasource, createAnalysis, deleteAnalysisByApi } from './utils/api.js';
import { readyTimeoutMs } from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

// ── Real e2e build preview tests (no WS mocking) ───────────────────────────

async function expectVisibleEventually(locator: Locator) {
	await expect(locator).toBeVisible({ timeout: readyTimeoutMs() });
}

async function deleteBestEffort(
	page: Page,
	endpoint: string,
	expectedStatuses: Set<number>
): Promise<void> {
	const response = await page.request.delete(endpoint, { timeout: 5_000 }).catch(() => null);
	if (!response || expectedStatuses.has(response.status())) return;
	throw new Error(`Cleanup DELETE ${endpoint} returned HTTP ${response.status()}`);
}

async function cleanupBuildPreviewResources(
	page: Page,
	analysisId: string,
	datasourceId: string
): Promise<void> {
	await deleteBestEffort(
		page,
		`/api/v1/compute/engine/analysis/${analysisId}`,
		new Set([204, 404, 409])
	);
	const analysisDeleteStatus = await deleteAnalysisByApi(page, analysisId);
	if (![204, 404].includes(analysisDeleteStatus)) {
		throw new Error(
			`Cleanup DELETE /api/v1/analysis/${analysisId} returned HTTP ${analysisDeleteStatus}`
		);
	}
	await deleteBestEffort(page, `/api/v1/datasource/${datasourceId}`, new Set([202, 204, 404]));
}

test.describe('Build Preview – real build lifecycle', () => {
	test('clicking Build queues the run and the preview opens only from the engine status control', async ({
		page,
		request
	}) => {
		const dsName = `e2e-bprev-real-ds-${uid()}`;
		const aName = `E2E BPrev Real ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expectVisibleEventually(buildBtn);
			await buildBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).not.toBeVisible();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expectVisibleEventually(openPreviewBtn);
			await openPreviewBtn.click();

			await expectVisibleEventually(preview);

			const closeBtn = page.locator('[aria-label="Close build preview"]');
			await expect(closeBtn).toBeVisible();

			const progressBar = page.locator('[data-testid="build-progress-bar"]');
			await expect(progressBar).toBeVisible();

			await screenshot(page, 'build-preview', 'real-build-terminal');
		} finally {
			await cleanupBuildPreviewResources(page, aId, dsId);
		}
	});

	test('close button dismisses the Build Preview modal', async ({ page, request }) => {
		const dsName = `e2e-bprev-close-ds-${uid()}`;
		const aName = `E2E BPrev Close ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await gotoAnalysisEditor(page, aId);

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expectVisibleEventually(buildBtn);
			await buildBtn.click();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expectVisibleEventually(openPreviewBtn);
			await openPreviewBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expectVisibleEventually(preview);

			const closeBtn = page.locator('[aria-label="Close build preview"]');
			await expect(closeBtn).toBeVisible();
			await closeBtn.click();

			await expect(preview).not.toBeVisible({ timeout: 5_000 });

			await screenshot(page, 'build-preview', 'real-build-modal-closed');
		} finally {
			await cleanupBuildPreviewResources(page, aId, dsId);
		}
	});
});
