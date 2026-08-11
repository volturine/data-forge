import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { createDatasource, createAnalysis, findAnalysisIdByName } from './utils/api.js';
import {
	deleteAnalysisViaUI,
	deleteDatasourceViaUI,
	freeWarmEnginesViaUI
} from './utils/ui-cleanup.js';
import { readyTimeoutMs } from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

// ── Real e2e build preview tests (no WS mocking) ───────────────────────────

async function expectVisibleEventually(locator: Locator) {
	await expect(locator).toBeVisible({ timeout: readyTimeoutMs() });
}

async function cleanupBuildPreviewResources(
	page: Page,
	analysisName: string,
	datasourceName: string,
	buildId?: string,
	analysisId?: string
): Promise<void> {
	// After terminal build status, free warm containers then delete via UI.
	const aId = analysisId ?? findAnalysisIdByName(analysisName) ?? undefined;
	await freeWarmEnginesViaUI(page, {
		buildIds: buildId ? [buildId] : [],
		analysisIds: aId ? [aId] : []
	}).catch(() => undefined);
	await deleteAnalysisViaUI(page, analysisName).catch(() => undefined);
	await deleteDatasourceViaUI(page, datasourceName).catch(() => undefined);
}

async function startBuildAndCaptureId(page: Page): Promise<string | undefined> {
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expectVisibleEventually(buildBtn);
	const started = page.waitForResponse(
		(response) => {
			if (response.request().method() !== 'POST' || !response.ok()) return false;
			const path = new URL(response.url()).pathname;
			return path === '/api/v1/compute/builds' || path === '/api/v1/compute/builds/';
		},
		{ timeout: readyTimeoutMs() }
	);
	await buildBtn.click();
	const payload = (await (await started).json().catch(() => null)) as {
		build_id?: string;
		id?: string;
	} | null;
	return payload?.build_id ?? payload?.id;
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
		let buildId: string | undefined;
		try {
			await gotoAnalysisEditor(page, aId);
			buildId = await startBuildAndCaptureId(page);

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).not.toBeVisible();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expectVisibleEventually(openPreviewBtn);
			await openPreviewBtn.click();

			await expectVisibleEventually(preview);

			const closeBtn = page.locator('[aria-label="Close build preview"]');
			await expect(closeBtn).toBeVisible();

			// Progress bar is always present; status may already be terminal under load.
			const progressBar = page.locator('[data-testid="build-progress-bar"]');
			await expect(progressBar).toBeVisible({ timeout: 5_000 });
			await expect(
				preview.getByText(/Complete|Running|Queued|Failed|Cancelled/i).first()
			).toBeVisible({ timeout: readyTimeoutMs() });

			await screenshot(page, 'build-preview', 'real-build-terminal');
		} finally {
			await cleanupBuildPreviewResources(page, aName, dsName, buildId, aId);
		}
	});

	test('close button dismisses the Build Preview modal', async ({ page, request }) => {
		const dsName = `e2e-bprev-close-ds-${uid()}`;
		const aName = `E2E BPrev Close ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		let buildId: string | undefined;
		try {
			await gotoAnalysisEditor(page, aId);
			buildId = await startBuildAndCaptureId(page);

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
			await cleanupBuildPreviewResources(page, aName, dsName, buildId, aId);
		}
	});
});
