import { expect, type Locator, type Page } from '@playwright/test';
import { readyTimeoutMs } from './readiness.js';

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
