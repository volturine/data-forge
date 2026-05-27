import type { Locator } from '@playwright/test';

import { test, expect } from './fixtures.js';
import { gotoAnalysisEditor } from './utils/analysis.js';
import { createDatasource, createAnalysis, shutdownEngine } from './utils/api.js';
import {
	createCleanupPage,
	deleteAnalysisViaUI,
	deleteDatasourceViaUI
} from './utils/ui-cleanup.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

// ── Real e2e build preview tests (no WS mocking) ───────────────────────────

async function expectVisibleEventually(locator: Locator) {
	let lastError: unknown;
	for (let attempt = 0; attempt < 3; attempt += 1) {
		try {
			await expect(locator).toBeVisible({ timeout: 5_000 });
			return;
		} catch (error) {
			lastError = error;
		}
	}
	throw lastError;
}

test.describe('Build Preview – real build lifecycle', () => {
	test('clicking Build queues the run and the preview opens only from the engine status control', async ({
		page,
		request,
		browser,
		workerAuth
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
			const { page: cleanupPage, context } = await createCleanupPage(
				browser,
				workerAuth.workerIndex
			);
			try {
				await shutdownEngine(request, aId);
				await deleteAnalysisViaUI(cleanupPage, aName);
				await deleteDatasourceViaUI(cleanupPage, dsName);
			} finally {
				await cleanupPage.close();
				await context.close();
			}
		}
	});

	test('close button dismisses the Build Preview modal', async ({
		page,
		request,
		browser,
		workerAuth
	}) => {
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
			const { page: cleanupPage, context } = await createCleanupPage(
				browser,
				workerAuth.workerIndex
			);
			try {
				await shutdownEngine(request, aId);
				await deleteAnalysisViaUI(cleanupPage, aName);
				await deleteDatasourceViaUI(cleanupPage, dsName);
			} finally {
				await cleanupPage.close();
				await context.close();
			}
		}
	});
});
