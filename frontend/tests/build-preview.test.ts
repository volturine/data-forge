import { test, expect } from '@playwright/test';
import {
	createDatasource,
	createAnalysis,
	createLargeDatasource,
	createMultiStepAnalysis
} from './utils/api.js';
import { deleteAnalysisViaUI, deleteDatasourceViaUI } from './utils/ui-cleanup.js';
import { waitForLayoutReady } from './utils/readiness.js';
import { uid } from './utils/uid.js';
import { screenshot } from './utils/visual.js';

// ── Real e2e build preview tests (no WS mocking) ───────────────────────────

test.describe('Build Preview – real build lifecycle', () => {
	test('clicking Build queues the run and the preview opens only from the engine status control', async ({
		page,
		request
	}) => {
		test.setTimeout(120_000);
		const dsName = `e2e-bprev-real-ds-${uid()}`;
		const aName = `E2E BPrev Real ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[role="application"]')).toBeVisible({ timeout: 15_000 });

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).not.toBeVisible();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
			await openPreviewBtn.click();

			await expect(page.getByText('Build Preview')).toBeVisible({ timeout: 10_000 });
			await expect(preview).toBeVisible({ timeout: 5_000 });

			const closeBtn = page.locator('[aria-label="Close build preview"]');
			await expect(closeBtn).toBeVisible();

			const progressBar = page.locator('[data-testid="build-progress-bar"]');
			await expect(progressBar).toBeVisible();

			const terminal = preview
				.getByText('Complete', { exact: true })
				.or(preview.getByText('Failed', { exact: true }));
			await expect(terminal).toBeVisible({ timeout: 60_000 });

			await screenshot(page, 'build-preview', 'real-build-terminal');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('completed build shows steps and results from real execution', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsName = `e2e-bprev-steps-ds-${uid()}`;
		const aName = `E2E BPrev Steps ${uid()}`;
		const dsId = await createLargeDatasource(request, dsName, 500);
		const aId = await createMultiStepAnalysis(request, aName, dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[role="application"]')).toBeVisible({ timeout: 15_000 });

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
			await openPreviewBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).toBeVisible({ timeout: 10_000 });

			await expect(preview.getByText('Complete', { exact: true })).toBeVisible({ timeout: 60_000 });

			await screenshot(page, 'build-preview', 'real-build-complete-with-steps');

			const progressBar = page.locator('[data-testid="build-progress-bar"]');
			await expect(progressBar).toBeVisible({ timeout: 5_000 });

			const stepsPanel = page.locator('[data-testid="build-steps-panel"]');
			await expect(stepsPanel).toBeVisible({ timeout: 5_000 });

			const results = page.locator('[data-testid="build-results"]');
			await expect(results).toBeVisible({ timeout: 5_000 });
			await expect(results.getByText('Source 1')).toBeVisible();
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});

	test('close button dismisses the Build Preview modal', async ({ page, request }) => {
		test.setTimeout(120_000);
		const dsName = `e2e-bprev-close-ds-${uid()}`;
		const aName = `E2E BPrev Close ${uid()}`;
		const dsId = await createDatasource(request, dsName);
		const aId = await createAnalysis(request, aName, dsId);
		try {
			await page.goto(`/analysis/${aId}`);
			await waitForLayoutReady(page);
			await expect(page.locator('[role="application"]')).toBeVisible({ timeout: 15_000 });

			const buildBtn = page.locator('[data-testid="output-build-button"]');
			await expect(buildBtn).toBeVisible({ timeout: 10_000 });
			await buildBtn.click();

			const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
			await expect(openPreviewBtn).toBeVisible({ timeout: 10_000 });
			await openPreviewBtn.click();

			const preview = page.locator('[data-testid="build-preview"]');
			await expect(preview).toBeVisible({ timeout: 10_000 });

			const closeBtn = page.locator('[aria-label="Close build preview"]');
			await expect(closeBtn).toBeVisible();
			await closeBtn.click();

			await expect(preview).not.toBeVisible({ timeout: 5_000 });

			await screenshot(page, 'build-preview', 'real-build-modal-closed');
		} finally {
			await deleteAnalysisViaUI(page, aName);
			await deleteDatasourceViaUI(page, dsName);
		}
	});
});
