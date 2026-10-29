import { expect, type Locator, type Page } from '@playwright/test';
import { gotoAnalysisEditor } from './analysis.js';
import { readyTimeoutMs, waitForLayoutReady } from './readiness.js';

export async function waitForBuildPreview(
	page: Page,
	timeout = readyTimeoutMs()
): Promise<Locator> {
	const preview = page.locator('[data-testid="build-preview"]');
	await expect(preview).toBeVisible({ timeout });
	return preview;
}

export async function waitForBuildPreviewId(
	page: Page,
	timeout = readyTimeoutMs()
): Promise<string> {
	const preview = await waitForBuildPreview(page, timeout);
	const id = preview.locator('[data-testid="build-preview-id"]');
	await expect(id).toHaveText(/\S/, { timeout });
	return ((await id.textContent()) ?? '').trim();
}

export async function gotoMonitoringBuilds(page: Page, analysisId?: string) {
	const params = new URLSearchParams({ tab: 'builds' });
	if (analysisId) params.set('analysis_id', analysisId);
	await page.goto(`/monitoring?${params.toString()}`);
	await waitForLayoutReady(page);
	await expect(page.getByRole('tab', { name: 'Builds', selected: true })).toBeVisible({
		timeout: 5_000
	});
	await expect(page.locator('#panel-builds')).toBeVisible({ timeout: 5_000 });
}

/**
 * Starts a build from the analysis editor and returns its id. The id comes from the
 * start response so callers can navigate away immediately (e.g. monitoring cancel).
 * Unless `openPreview` is false, the build preview must show that same id.
 */
export async function startBuildFromAnalysisPage(
	page: Page,
	analysisId: string,
	options: { openPreview?: boolean } = {}
): Promise<string> {
	const openPreview = options.openPreview ?? true;
	await gotoAnalysisEditor(page, analysisId);
	const buildBtn = page.locator('[data-testid="output-build-button"]');
	await expect(buildBtn).toBeVisible({ timeout: 5_000 });
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

	const existingPreview = page.locator('[data-testid="build-preview"]');
	if (!(await existingPreview.isVisible().catch(() => false))) {
		const openPreviewBtn = page.locator('[data-testid="output-build-preview-trigger"]');
		await expect(openPreviewBtn).toBeVisible({ timeout: readyTimeoutMs() });
		await openPreviewBtn.click({ timeout: 5_000 });
	}
	const previewId = await waitForBuildPreviewId(page);
	expect(previewId).toBe(buildId);
	return buildId;
}

/**
 * Waits until `row` is visible in the Builds history panel. Fails fast if the history
 * reports a load error. The returned locator is the first match.
 */
export async function waitForBuildRow(
	panel: Locator,
	row: Locator,
	label: string,
	timeout = 15_000
): Promise<Locator> {
	// A build can briefly render more than one matching row; `first()` keeps the
	// visibility check out of strict mode.
	const target = row.first();
	await expect
		.poll(
			async () => {
				const failedToLoad = panel.getByText(/Failed to load builds/i).first();
				if (await failedToLoad.isVisible().catch(() => false)) {
					throw new Error(`Build history failed while waiting for ${label}`);
				}
				return target.isVisible().catch(() => false);
			},
			{ timeout, intervals: [100, 250, 500] }
		)
		.toBe(true);
	return target;
}

export async function waitForBuildRowById(
	_page: Page,
	panel: Locator,
	buildId: string,
	statuses: Array<'queued' | 'running' | 'completed' | 'failed' | 'cancelled'>,
	timeout = 15_000
): Promise<Locator> {
	const row = panel.locator(
		statuses
			.map((status) => `[data-build-row="${buildId}"][data-build-status="${status}"]`)
			.join(', ')
	);
	return waitForBuildRow(panel, row, `build row ${buildId}`, timeout);
}
