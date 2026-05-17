import { expect, type Page } from '@playwright/test';
import { waitForAppShell, waitForDatasourceList } from './readiness.js';
import { dialogByTextbox } from './locators.js';

const SIDEBAR = 'aside[aria-label="Main navigation"]';

/**
 * Switch to a namespace via the sidebar picker.
 * If the namespace doesn't exist yet, creates it inline.
 * Preserves the current route — waits for sidebar to reflect the new namespace.
 */
export async function switchNamespace(page: Page, name: string): Promise<void> {
	await page.getByRole('button', { name: 'Select namespace' }).click();
	const dialog = dialogByTextbox(page, 'Search namespaces');
	await expect(dialog).toBeVisible({ timeout: 5_000 });

	const search = dialog.getByRole('textbox', { name: 'Search namespaces' });
	await search.fill(name);

	const exact = dialog.locator(`[data-namespace-option="${name}"]`);
	const create = dialog.locator(`[data-namespace-create="${name}"]`);
	await expect(exact.or(create)).toBeVisible({ timeout: 8_000 });

	if (await exact.isVisible()) {
		await exact.click();
	} else {
		await create.click();
	}

	await expect(dialog).not.toBeVisible({ timeout: 5_000 });
	await expect(page.locator(SIDEBAR).getByText(name)).toBeVisible({ timeout: 5_000 });
}

/**
 * Assert the current active namespace shown in the sidebar.
 */
export async function expectNamespace(page: Page, name: string): Promise<void> {
	await expect(page.locator(SIDEBAR).getByText(name)).toBeVisible({ timeout: 5_000 });
}

/**
 * Switch namespace while on the datasources page and wait for the list to refresh.
 */
export async function switchNamespaceAndGoToDatasources(page: Page, name: string): Promise<void> {
	await waitForAppShell(page);
	await switchNamespace(page, name);
	await waitForDatasourceList(page);
}
