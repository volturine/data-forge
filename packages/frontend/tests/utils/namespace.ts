import { expect, type Page } from '@playwright/test';
import { readyTimeoutMs, waitForAppShell, waitForDatasourceList } from './readiness.js';
import { dialogByTextbox } from './locators.js';

const SIDEBAR = 'aside[aria-label="Main navigation"]';

/**
 * The namespace every test runs in.
 *
 * All Playwright shards share one app stack and one namespace: tests isolate
 * themselves by unique resource names, not by namespace. Namespaces are a
 * product feature, exercised by namespace-isolation.test.ts alone.
 */
export const DEFAULT_NAMESPACE = process.env.DEFAULT_NAMESPACE?.trim() || 'default';

/**
 * Switch to a namespace via the sidebar picker.
 * If the namespace doesn't exist yet, creates it inline.
 * Preserves the current route — waits for sidebar to reflect the new namespace.
 */
export async function switchNamespace(page: Page, name: string): Promise<void> {
	await waitForAppShell(page);
	const picker = page.getByRole('button', { name: 'Select namespace' });
	if ((await picker.textContent())?.trim() === name) return;

	await picker.click();
	const dialog = dialogByTextbox(page, 'Search namespaces');
	await expect(dialog).toBeVisible({ timeout: 5_000 });

	const search = dialog.getByRole('textbox', { name: 'Search namespaces' });
	await search.fill(name);

	const exact = dialog.locator(`[data-namespace-option="${name}"]`);
	const create = dialog.locator(`[data-namespace-create="${name}"]`);
	// Namespace list is server-filtered after search; under CI load the option
	// (or create row) can lag behind the fill.
	await expect(exact.or(create)).toBeVisible({ timeout: readyTimeoutMs() });

	if (await exact.isVisible()) {
		await exact.click();
	} else {
		await create.click();
	}

	await expect
		.poll(
			async () => {
				if (!(await dialog.isVisible().catch(() => false))) return 'closed';
				const alert = dialog.getByRole('alert');
				if (await alert.isVisible().catch(() => false)) {
					throw new Error(`Namespace switch failed: ${await alert.innerText()}`);
				}
				return 'provisioning';
			},
			{ timeout: readyTimeoutMs(), message: `Namespace ${name} did not finish switching` }
		)
		.toBe('closed');
	await expect(page.locator(SIDEBAR).getByText(name)).toBeVisible({ timeout: readyTimeoutMs() });
	await waitForAppShell(page);
}

/**
 * Assert the current active namespace shown in the sidebar.
 */
export async function expectNamespace(page: Page, name: string): Promise<void> {
	await expect(page.locator(SIDEBAR).getByText(name)).toBeVisible({ timeout: 5_000 });
}

/** Restore the shared worker context after a test that changes namespace. */
export async function restoreDefaultNamespace(page: Page): Promise<void> {
	await waitForAppShell(page);
	const target = DEFAULT_NAMESPACE;
	const picker = page.getByRole('button', { name: 'Select namespace' });
	if ((await picker.textContent())?.trim() === target) return;
	await switchNamespace(page, target);
}

/**
 * Switch namespace while on the datasources page and wait for the list to refresh.
 */
export async function switchNamespaceAndGoToDatasources(page: Page, name: string): Promise<void> {
	await waitForAppShell(page);
	await switchNamespace(page, name);
	await waitForDatasourceList(page);
}
