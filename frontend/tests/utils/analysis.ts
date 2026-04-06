import { expect, type Locator, type Page } from '@playwright/test';
import { waitForLayoutReady } from './readiness.js';

/**
 * Wait for the analysis editor to be fully interactive. Ensures:
 *  1. `[role="application"]` has mounted (analysis query resolved).
 *  2. At least one step button (`button[data-step]`) is visible,
 *     expanding the left pane if it was auto-collapsed.
 *
 * This does NOT depend on the "Operations" heading which becomes invisible
 * when the left pane is collapsed (`visibility: hidden; width: 0`).
 */
async function waitForAnalysisEditor(page: Page, timeout = 30_000): Promise<void> {
	await expect(page.locator('[role="application"]')).toBeVisible({ timeout });

	const anyStepButton = page.locator('button[data-step]').first();
	const alreadyVisible = await anyStepButton.isVisible().catch(() => false);

	if (!alreadyVisible) {
		const expandBtn = page.locator('button[title="Expand panels"]').first();
		const canExpand = await expandBtn.isVisible().catch(() => false);
		if (canExpand) {
			await expandBtn.click();
		}
	}

	await expect(anyStepButton).toBeVisible({ timeout: 10_000 });
}

/**
 * Navigate to an analysis page and wait until the step library is fully
 * rendered and interactable. Handles the case where the left pane is
 * auto-collapsed on narrow viewports by expanding it first.
 *
 * Readiness chain:
 *  1. Layout ready (shell hydrated, `<main>` visible).
 *  2. `[role="application"]` mounted (analysis query succeeded).
 *  3. A step button is visible (expanding collapsed pane if needed).
 */
export async function gotoAnalysisEditor(page: Page, analysisId: string): Promise<void> {
	await page.goto(`/analysis/${analysisId}`);
	await waitForLayoutReady(page);
	await waitForAnalysisEditor(page);
}

/**
 * After a `page.reload()` inside the analysis editor, re-confirm readiness.
 * Same gates as `gotoAnalysisEditor` but without the navigation step.
 */
export async function waitForEditorReload(page: Page): Promise<void> {
	await waitForLayoutReady(page);
	await waitForAnalysisEditor(page);
}

/**
 * Navigate to an analysis, wait for the step library, add a step,
 * click "edit" on the resulting canvas node to open its config panel.
 * Returns the config panel locator.
 */
export async function addStepAndOpenConfig(
	page: Page,
	analysisId: string,
	stepType: string
): Promise<Locator> {
	await gotoAnalysisEditor(page, analysisId);
	await page.locator(`button[data-step="${stepType}"]`).click();

	const canvasNode = page.locator(`[data-step-type="${stepType}"]`).first();
	await expect(canvasNode).toBeVisible({ timeout: 5_000 });

	await canvasNode.locator('[data-action="edit"]').click();

	const configPanel = page.locator(`[data-step-config="${stepType}"]`);
	await expect(configPanel).toBeVisible({ timeout: 8_000 });
	return configPanel;
}
