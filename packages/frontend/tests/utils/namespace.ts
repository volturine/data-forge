import { expect, type Page } from '@playwright/test';
import { waitForAppShell, waitForDatasourceList } from './readiness.js';
import { dialogByTextbox } from './locators.js';

const SIDEBAR = 'aside[aria-label="Main navigation"]';

/**
 * Namespace this run's tests operate in.
 *
 * Parallel Playwright shards share one app stack, so each shard works inside
 * its own namespace (its own bucket, engine credentials, and data) to avoid
 * cross-shard interference. Empty env = the app's default namespace.
 */
export function shardNamespace(): string {
	return process.env.E2E_NAMESPACE || 'default';
}

/**
 * Seed a fresh browser profile with the shard namespace.
 *
 * The app stores the active namespace in IndexedDB (per profile), which
 * storageState does not carry — a seeded first navigation does. No-op when the
 * run uses the default namespace.
 */
export async function seedShardNamespace(page: Page): Promise<void> {
	const target = shardNamespace();
	if (target === 'default') return;
	await page.goto(`/?namespace=${target}`, { waitUntil: 'domcontentloaded', timeout: 15_000 });
	await waitForAppShell(page);
}

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
	// Namespace list is server-filtered after search; under CI load the option
	// (or create row) can lag behind the fill.
	await expect(exact.or(create)).toBeVisible({ timeout: 15_000 });

	if (await exact.isVisible()) {
		await exact.click();
	} else {
		await create.click();
	}

	await expect(dialog).not.toBeVisible({ timeout: 5_000 });
	await expect(page.locator(SIDEBAR).getByText(name)).toBeVisible({ timeout: 15_000 });
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
	const target = shardNamespace();
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
