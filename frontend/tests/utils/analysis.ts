import { expect, type Locator, type Page } from '@playwright/test';

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
	await page.goto(`/analysis/${analysisId}`);
	await expect(page.locator(`button[data-step="${stepType}"]`)).toBeVisible({ timeout: 15_000 });
	await page.locator(`button[data-step="${stepType}"]`).click();

	const canvasNode = page.locator(`[data-step-type="${stepType}"]`).first();
	await expect(canvasNode).toBeVisible({ timeout: 5_000 });

	await canvasNode.locator('[data-action="edit"]').click();

	const configPanel = page.locator(`[data-step-config="${stepType}"]`);
	await expect(configPanel).toBeVisible({ timeout: 8_000 });
	return configPanel;
}
