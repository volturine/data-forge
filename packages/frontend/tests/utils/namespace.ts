import { expect, type Page } from '@playwright/test';
import { readyTimeoutMs, waitForAppShell } from './readiness.js';

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
 * If the namespace doesn't exist yet, creates it in the namespace dialog.
 * Preserves the current route — waits for sidebar to reflect the new namespace.
 */
export async function switchNamespace(
	page: Page,
	name: string,
	provisioningTimeoutMs = readyTimeoutMs()
): Promise<void> {
	await waitForAppShell(page);
	const picker = page.getByRole('button', { name: 'Select namespace' });
	if ((await picker.textContent())?.trim() === name) return;

	await picker.click();
	const dialog = page.locator('[role="dialog"][aria-labelledby="namespace-picker-title"]');
	await expect(dialog).toBeVisible({ timeout: 5_000 });

	const search = dialog.getByRole('textbox', { name: 'Search namespaces' });
	await search.fill(name);

	const exact = dialog.locator(`[data-namespace-option="${name}"]`);
	const noResults = dialog.getByText('No namespaces match your search.');
	// The debounced filter and initial query can both lag behind the search input.
	await expect(exact.or(noResults)).toBeVisible({ timeout: readyTimeoutMs() });

	if (await exact.isVisible()) {
		await exact.click();
	} else {
		await dialog.getByRole('button', { name: 'New namespace' }).click();
		await dialog.locator('#namespace-create-name').fill(name);
		const create = dialog.locator(`[data-namespace-create="${name}"]`);
		await expect(create).toBeEnabled({ timeout: readyTimeoutMs() });
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
			{ timeout: provisioningTimeoutMs, message: `Namespace ${name} did not finish switching` }
		)
		.toBe('closed');
	await expect(page.locator(SIDEBAR).getByText(name)).toBeVisible({
		timeout: provisioningTimeoutMs
	});
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
